/**
 * Knowledge Store service.
 *
 * Implements document indexing (text, PDF, HTML up to 50MB),
 * chunking, embedding generation, and Qdrant storage.
 * Also manages user knowledge items with a 500-item capacity limit.
 *
 * Requirements: 4.4, 4.5, 7.3
 */

import { randomUUID } from "node:crypto";
import type {
  KnowledgeStoreManager,
  KnowledgeItem,
} from "../interfaces/knowledge-store.js";
import type { DocumentInput, IndexResult } from "../interfaces/rag-pipeline.js";
import { KNOWLEDGE_STORE_MAX_ITEMS } from "../config/defaults.js";

/** Maximum document size in megabytes */
const MAX_DOCUMENT_SIZE_MB = 50;

/** Target chunk size in characters (~500 tokens ≈ 2000 chars) */
const CHUNK_SIZE_CHARS = 2000;

/** Overlap between chunks in characters for context continuity */
const CHUNK_OVERLAP_CHARS = 200;

/** Shape of embedding service response */
interface EmbeddingResponse {
  embedding: number[];
}

export class KnowledgeStoreService implements KnowledgeStoreManager {
  /** In-memory store: userId → Map<itemId, KnowledgeItem> */
  private readonly items: Map<string, Map<string, KnowledgeItem>> = new Map();

  private readonly embeddingUrl: string;
  private readonly qdrantUrl: string;
  private readonly collectionName: string;

  constructor(options?: {
    embeddingUrl?: string;
    qdrantUrl?: string;
    collectionName?: string;
  }) {
    this.embeddingUrl =
      options?.embeddingUrl ??
      process.env["EMBEDDING_URL"] ??
      "http://localhost:8003";
    this.qdrantUrl =
      options?.qdrantUrl ??
      process.env["QDRANT_URL"] ??
      "http://localhost:6333";
    this.collectionName = options?.collectionName ?? "documents";
  }

  /**
   * Store a knowledge item for a user.
   * Enforces 500-item capacity limit per user.
   * Returns the generated item ID.
   */
  async storeItem(userId: string, item: KnowledgeItem): Promise<string> {
    const count = await this.getItemCount(userId);
    if (count >= KNOWLEDGE_STORE_MAX_ITEMS) {
      throw new Error(
        `Knowledge Store capacity exceeded: user ${userId} has reached the maximum of ${KNOWLEDGE_STORE_MAX_ITEMS} items`
      );
    }

    const itemId = randomUUID();
    const storedItem: KnowledgeItem = {
      ...item,
      id: itemId,
      createdAt: item.createdAt ?? new Date(),
    };

    let userItems = this.items.get(userId);
    if (!userItems) {
      userItems = new Map();
      this.items.set(userId, userItems);
    }

    userItems.set(itemId, storedItem);
    return itemId;
  }

  /**
   * Remove an item from the user's knowledge store.
   * Throws if the item does not exist.
   */
  async removeItem(userId: string, itemId: string): Promise<void> {
    const userItems = this.items.get(userId);
    if (!userItems || !userItems.has(itemId)) {
      throw new Error(
        `Item not found: ${itemId} for user ${userId}`
      );
    }
    userItems.delete(itemId);
  }

  /**
   * Get all stored items for a user.
   */
  async getItems(userId: string): Promise<KnowledgeItem[]> {
    const userItems = this.items.get(userId);
    if (!userItems) {
      return [];
    }
    return Array.from(userItems.values());
  }

  /**
   * Count items for a user.
   */
  async getItemCount(userId: string): Promise<number> {
    const userItems = this.items.get(userId);
    return userItems ? userItems.size : 0;
  }

  /**
   * Index a document: validate size, extract text, chunk, embed, store in Qdrant.
   *
   * Accepts text, PDF, and HTML formats up to 50MB.
   * Target: complete indexing within 60 seconds for documents <= 10MB.
   */
  async indexDocument(document: DocumentInput): Promise<IndexResult> {
    const startTime = performance.now();
    const documentId = randomUUID();

    // Validate document size
    if (document.sizeMb > MAX_DOCUMENT_SIZE_MB) {
      return {
        documentId,
        chunksCreated: 0,
        indexTimeMs: performance.now() - startTime,
        success: false,
      };
    }

    try {
      // Step 1: Extract text based on format
      const text = this.extractText(document.content, document.format);

      // Step 2: Chunk the text
      const chunks = this.chunkText(text);

      // If no chunks produced (empty document), return success with 0 chunks
      if (chunks.length === 0) {
        return {
          documentId,
          chunksCreated: 0,
          indexTimeMs: performance.now() - startTime,
          success: true,
        };
      }

      // Step 3: Generate embeddings for each chunk
      const embeddings = await this.generateEmbeddings(chunks);

      // Step 4: Store chunks with embeddings in Qdrant
      await this.storeInQdrant(documentId, chunks, embeddings, document.metadata);

      const indexTimeMs = performance.now() - startTime;

      return {
        documentId,
        chunksCreated: chunks.length,
        indexTimeMs,
        success: true,
      };
    } catch (error: unknown) {
      const indexTimeMs = performance.now() - startTime;
      return {
        documentId,
        chunksCreated: 0,
        indexTimeMs,
        success: false,
      };
    }
  }

  /**
   * Extract text content from a document buffer based on format.
   */
  private extractText(content: Buffer, format: "text" | "pdf" | "html"): string {
    switch (format) {
      case "text":
        return content.toString("utf-8");
      case "html":
        return this.extractTextFromHtml(content.toString("utf-8"));
      case "pdf":
        return this.extractTextFromPdf(content);
      default:
        return content.toString("utf-8");
    }
  }

  /**
   * Simple HTML text extraction — strips tags and decodes common entities.
   */
  private extractTextFromHtml(html: string): string {
    // Remove script and style tags with their content
    let text = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "");
    text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "");
    // Replace block-level elements with newlines for paragraph separation
    text = text.replace(/<\/(p|div|h[1-6]|li|tr|br\s*\/?)>/gi, "\n");
    text = text.replace(/<br\s*\/?>/gi, "\n");
    // Remove remaining tags
    text = text.replace(/<[^>]+>/g, "");
    // Decode common HTML entities
    text = text.replace(/&amp;/g, "&");
    text = text.replace(/&lt;/g, "<");
    text = text.replace(/&gt;/g, ">");
    text = text.replace(/&quot;/g, '"');
    text = text.replace(/&#39;/g, "'");
    text = text.replace(/&nbsp;/g, " ");
    // Normalize whitespace
    text = text.replace(/\n{3,}/g, "\n\n");
    text = text.trim();
    return text;
  }

  /**
   * Simple PDF text extraction — extracts readable ASCII/UTF-8 text segments.
   * For production, a full PDF parser (e.g., pdf-parse) would be used.
   */
  private extractTextFromPdf(content: Buffer): string {
    // Simple extraction: find text between BT/ET markers or extract readable strings
    const rawText = content.toString("utf-8");
    // Extract text that appears between parentheses in PDF content streams
    const textSegments: string[] = [];
    const regex = /\(([^)]+)\)/g;
    let match = regex.exec(rawText);
    while (match !== null) {
      const segment = match[1];
      if (segment && segment.length > 1) {
        textSegments.push(segment);
      }
      match = regex.exec(rawText);
    }

    if (textSegments.length > 0) {
      return textSegments.join(" ");
    }

    // Fallback: extract printable characters
    const printable = rawText.replace(/[^\x20-\x7E\n\r\t]/g, " ");
    return printable.replace(/\s{2,}/g, " ").trim();
  }

  /**
   * Split text into chunks of approximately CHUNK_SIZE_CHARS characters
   * with CHUNK_OVERLAP_CHARS overlap. Splits on paragraph boundaries where possible.
   */
  private chunkText(text: string): string[] {
    if (text.length === 0) {
      return [];
    }

    if (text.length <= CHUNK_SIZE_CHARS) {
      return [text];
    }

    const chunks: string[] = [];
    let start = 0;

    while (start < text.length) {
      let end = start + CHUNK_SIZE_CHARS;

      if (end >= text.length) {
        chunks.push(text.slice(start));
        break;
      }

      // Try to find a paragraph break near the end
      const searchWindow = text.slice(
        Math.max(start, end - 200),
        end + 200
      );
      const paragraphBreak = searchWindow.lastIndexOf("\n\n");

      if (paragraphBreak > 0) {
        end = Math.max(start, end - 200) + paragraphBreak + 2;
      } else {
        // Fall back to sentence boundary
        const sentenceEnd = text.lastIndexOf(". ", end);
        if (sentenceEnd > start + CHUNK_SIZE_CHARS / 2) {
          end = sentenceEnd + 2;
        }
      }

      chunks.push(text.slice(start, end));
      start = end - CHUNK_OVERLAP_CHARS;
    }

    return chunks;
  }

  /**
   * Generate embeddings for an array of text chunks via the embedding service.
   */
  private async generateEmbeddings(chunks: string[]): Promise<number[][]> {
    const embeddings: number[][] = [];

    for (const chunk of chunks) {
      const response = await fetch(`${this.embeddingUrl}/embed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: chunk }),
      });

      if (!response.ok) {
        throw new Error(
          `Embedding service error: ${response.status} ${response.statusText}`
        );
      }

      const data = (await response.json()) as EmbeddingResponse;
      embeddings.push(data.embedding);
    }

    return embeddings;
  }

  /**
   * Store document chunks with embeddings in Qdrant.
   */
  private async storeInQdrant(
    documentId: string,
    chunks: string[],
    embeddings: number[][],
    metadata: Record<string, string>
  ): Promise<void> {
    const points = chunks.map((chunk, index) => ({
      id: randomUUID(),
      vector: embeddings[index],
      payload: {
        documentId,
        content: chunk,
        chunkIndex: index,
        indexedAt: new Date().toISOString(),
        ...metadata,
      },
    }));

    const response = await fetch(
      `${this.qdrantUrl}/collections/${this.collectionName}/points`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points }),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Qdrant storage error: ${response.status} ${response.statusText}`
      );
    }
  }
}

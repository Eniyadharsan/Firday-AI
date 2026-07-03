/**
 * RAG Pipeline service.
 *
 * Implements document retrieval via embedding queries with sentence-transformers
 * and searching Qdrant vector store. Supports configurable top-k, relevance
 * threshold, and timeout handling.
 *
 * Requirements: 4.1, 4.2, 4.3, 4.7
 */

import { randomUUID } from "node:crypto";
import type {
  RAGPipeline,
  RetrievalConfig,
  RetrievalResult,
  RetrievedDocument,
  DocumentInput,
  IndexResult,
} from "../interfaces/rag-pipeline.js";

/** Shape of Qdrant search result points */
interface QdrantSearchPoint {
  id: string;
  score: number;
  payload?: {
    content?: string;
    source?: string;
    indexedAt?: string;
  };
}

/** Shape of Qdrant search response */
interface QdrantSearchResponse {
  result: QdrantSearchPoint[];
}

/** Shape of embedding service response */
interface EmbeddingResponse {
  embedding: number[];
}

export class RAGPipelineService implements RAGPipeline {
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
   * Retrieve relevant documents for a query.
   *
   * 1. Embeds the query text via the embedding service
   * 2. Searches Qdrant with the embedding vector, limit=topK
   * 3. Filters results where score >= relevanceThreshold
   * 4. Sorts by descending score
   * 5. Returns RetrievalResult with allBelowThreshold flag
   *
   * Implements a 10-second timeout (configurable via config.timeoutMs).
   */
  async retrieve(
    query: string,
    config: RetrievalConfig
  ): Promise<RetrievalResult> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), config.timeoutMs);

    try {
      // Step 1: Embed the query
      const embeddingStart = performance.now();
      const embedding = await this.embedQuery(query, controller.signal);
      const queryEmbeddingTimeMs = performance.now() - embeddingStart;

      // Step 2: Search Qdrant
      const searchStart = performance.now();
      const searchResults = await this.searchQdrant(
        embedding,
        config.topK,
        controller.signal
      );
      const searchTimeMs = performance.now() - searchStart;

      // Step 3: Filter by relevance threshold
      const filtered = searchResults.filter(
        (doc) => doc.similarityScore >= config.relevanceThreshold
      );

      // Step 4: Sort by descending score (should already be sorted from Qdrant, but ensure)
      filtered.sort((a, b) => b.similarityScore - a.similarityScore);

      // Step 5: Return results with allBelowThreshold flag
      const allBelowThreshold = filtered.length === 0;

      return {
        documents: filtered,
        allBelowThreshold,
        queryEmbeddingTimeMs,
        searchTimeMs,
      };
    } catch (error: unknown) {
      if (
        error instanceof Error &&
        (error.name === "AbortError" || error.name === "TimeoutError")
      ) {
        throw new Error(
          "RAG retrieval timed out: Knowledge Store failed to respond within the configured timeout"
        );
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Index a new document: validate format/size, extract text, chunk, embed, store in Qdrant.
   *
   * Accepts text, PDF, and HTML formats up to 50MB.
   * Target: complete indexing within 60 seconds for documents <= 10MB.
   */
  async indexDocument(document: DocumentInput): Promise<IndexResult> {
    const startTime = performance.now();
    const documentId = randomUUID();

    // Validate document size (max 50MB)
    if (document.sizeMb > 50) {
      return {
        documentId,
        chunksCreated: 0,
        indexTimeMs: performance.now() - startTime,
        success: false,
      };
    }

    // Validate format
    const validFormats: DocumentInput["format"][] = ["text", "pdf", "html"];
    if (!validFormats.includes(document.format)) {
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

      // Step 2: Chunk the document content (~512 tokens ≈ 2000 chars, 50 token overlap ≈ 200 chars)
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
      const embeddings = await this.generateChunkEmbeddings(chunks);

      // Step 4: Upsert chunks to Qdrant with metadata
      await this.upsertChunksToQdrant(documentId, chunks, embeddings, document.metadata);

      const indexTimeMs = performance.now() - startTime;

      return {
        documentId,
        chunksCreated: chunks.length,
        indexTimeMs,
        success: true,
      };
    } catch {
      return {
        documentId,
        chunksCreated: 0,
        indexTimeMs: performance.now() - startTime,
        success: false,
      };
    }
  }

  /**
   * Remove a document and all its chunks from Qdrant.
   */
  async removeDocument(documentId: string): Promise<void> {
    const response = await fetch(
      `${this.qdrantUrl}/collections/${this.collectionName}/points/delete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filter: {
            must: [
              {
                key: "documentId",
                match: { value: documentId },
              },
            ],
          },
        }),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Qdrant delete error: ${response.status} ${response.statusText}`
      );
    }
  }

  /**
   * Embed a query string using the embedding service.
   */
  private async embedQuery(
    query: string,
    signal: AbortSignal
  ): Promise<number[]> {
    const response = await fetch(`${this.embeddingUrl}/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: query }),
      signal,
    });

    if (!response.ok) {
      throw new Error(
        `Embedding service error: ${response.status} ${response.statusText}`
      );
    }

    const data = (await response.json()) as EmbeddingResponse;
    return data.embedding;
  }

  /**
   * Search Qdrant vector store with an embedding vector.
   */
  private async searchQdrant(
    vector: number[],
    limit: number,
    signal: AbortSignal
  ): Promise<RetrievedDocument[]> {
    const response = await fetch(
      `${this.qdrantUrl}/collections/${this.collectionName}/points/search`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vector,
          limit,
          with_payload: true,
        }),
        signal,
      }
    );

    if (!response.ok) {
      throw new Error(
        `Qdrant search error: ${response.status} ${response.statusText}`
      );
    }

    const data = (await response.json()) as QdrantSearchResponse;

    return data.result.map((point) => ({
      id: String(point.id),
      content: point.payload?.content ?? "",
      similarityScore: point.score,
      source: point.payload?.source ?? "unknown",
      indexedAt: point.payload?.indexedAt
        ? new Date(point.payload.indexedAt)
        : new Date(),
    }));
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
    let text = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "");
    text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "");
    text = text.replace(/<\/(p|div|h[1-6]|li|tr|br\s*\/?)>/gi, "\n");
    text = text.replace(/<br\s*\/?>/gi, "\n");
    text = text.replace(/<[^>]+>/g, "");
    text = text.replace(/&amp;/g, "&");
    text = text.replace(/&lt;/g, "<");
    text = text.replace(/&gt;/g, ">");
    text = text.replace(/&quot;/g, '"');
    text = text.replace(/&#39;/g, "'");
    text = text.replace(/&nbsp;/g, " ");
    text = text.replace(/\n{3,}/g, "\n\n");
    text = text.trim();
    return text;
  }

  /**
   * Simple PDF text extraction — extracts readable ASCII/UTF-8 text segments.
   */
  private extractTextFromPdf(content: Buffer): string {
    const rawText = content.toString("utf-8");
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

    const printable = rawText.replace(/[^\x20-\x7E\n\r\t]/g, " ");
    return printable.replace(/\s{2,}/g, " ").trim();
  }

  /** Target chunk size in characters (~512 tokens ≈ 2000 chars) */
  private static readonly CHUNK_SIZE_CHARS = 2000;

  /** Overlap between chunks in characters (~50 tokens ≈ 200 chars) */
  private static readonly CHUNK_OVERLAP_CHARS = 200;

  /**
   * Split text into chunks with overlap. Splits on paragraph boundaries where possible.
   */
  private chunkText(text: string): string[] {
    if (text.length === 0) {
      return [];
    }

    if (text.length <= RAGPipelineService.CHUNK_SIZE_CHARS) {
      return [text];
    }

    const chunks: string[] = [];
    let start = 0;

    while (start < text.length) {
      let end = start + RAGPipelineService.CHUNK_SIZE_CHARS;

      if (end >= text.length) {
        chunks.push(text.slice(start));
        break;
      }

      // Try to find a paragraph break near the end
      const searchWindow = text.slice(Math.max(start, end - 200), end + 200);
      const paragraphBreak = searchWindow.lastIndexOf("\n\n");

      if (paragraphBreak > 0) {
        end = Math.max(start, end - 200) + paragraphBreak + 2;
      } else {
        // Fall back to sentence boundary
        const sentenceEnd = text.lastIndexOf(". ", end);
        if (sentenceEnd > start + RAGPipelineService.CHUNK_SIZE_CHARS / 2) {
          end = sentenceEnd + 2;
        }
      }

      chunks.push(text.slice(start, end));
      start = end - RAGPipelineService.CHUNK_OVERLAP_CHARS;
    }

    return chunks;
  }

  /**
   * Generate embeddings for an array of text chunks via the embedding service.
   */
  private async generateChunkEmbeddings(chunks: string[]): Promise<number[][]> {
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
   * Upsert document chunks with embeddings into Qdrant.
   */
  private async upsertChunksToQdrant(
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

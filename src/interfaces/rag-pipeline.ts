/**
 * RAG Pipeline interfaces.
 *
 * Responsibility: Document retrieval, embedding, similarity search,
 * and source tracking.
 */

export interface RAGPipeline {
  /** Retrieve relevant documents for a query */
  retrieve(query: string, config: RetrievalConfig): Promise<RetrievalResult>;
  /** Index a new document */
  indexDocument(document: DocumentInput): Promise<IndexResult>;
  /** Remove a document */
  removeDocument(documentId: string): Promise<void>;
}

export interface RetrievalConfig {
  topK: number;             // 1-20, default 5
  relevanceThreshold: number; // 0.0-1.0, default 0.7
  timeoutMs: number;        // default 10000
}

export interface RetrievalResult {
  documents: RetrievedDocument[];
  allBelowThreshold: boolean;
  queryEmbeddingTimeMs: number;
  searchTimeMs: number;
}

export interface RetrievedDocument {
  id: string;
  content: string;
  similarityScore: number;
  source: string;
  indexedAt: Date;
}

export interface DocumentInput {
  content: Buffer;
  format: 'text' | 'pdf' | 'html';
  metadata: Record<string, string>;
  sizeMb: number;           // max 50MB
}

export interface IndexResult {
  documentId: string;
  chunksCreated: number;
  indexTimeMs: number;
  success: boolean;
}

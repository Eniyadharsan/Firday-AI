import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { RAGPipelineService } from "../../src/services/rag-pipeline.js";
import type { RetrievalConfig } from "../../src/interfaces/rag-pipeline.js";

// Default config for tests
const defaultConfig: RetrievalConfig = {
  topK: 5,
  relevanceThreshold: 0.7,
  timeoutMs: 10000,
};

// Helper to create a mock fetch response
function mockFetchResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
    headers: new Headers(),
    redirected: false,
    type: "basic",
    url: "",
    clone: () => mockFetchResponse(data, status),
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    blob: () => Promise.resolve(new Blob()),
    formData: () => Promise.resolve(new FormData()),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as Response;
}

describe("RAGPipelineService", () => {
  let service: RAGPipelineService;
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    service = new RAGPipelineService({
      embeddingUrl: "http://test-embedding:8003",
      qdrantUrl: "http://test-qdrant:6333",
      collectionName: "test-docs",
    });
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("retrieve()", () => {
    it("should return documents sorted by descending score above threshold", async () => {
      // Mock embedding response
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      // Mock Qdrant search response
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            {
              id: "doc-1",
              score: 0.95,
              payload: {
                content: "Document 1 content",
                source: "source-a",
                indexedAt: "2024-01-15T10:00:00Z",
              },
            },
            {
              id: "doc-2",
              score: 0.85,
              payload: {
                content: "Document 2 content",
                source: "source-b",
                indexedAt: "2024-01-14T10:00:00Z",
              },
            },
            {
              id: "doc-3",
              score: 0.75,
              payload: {
                content: "Document 3 content",
                source: "source-c",
                indexedAt: "2024-01-13T10:00:00Z",
              },
            },
          ],
        })
      );

      const result = await service.retrieve("test query", defaultConfig);

      expect(result.documents).toHaveLength(3);
      expect(result.documents[0]!.similarityScore).toBe(0.95);
      expect(result.documents[1]!.similarityScore).toBe(0.85);
      expect(result.documents[2]!.similarityScore).toBe(0.75);
      expect(result.allBelowThreshold).toBe(false);
    });

    it("should filter out documents below relevance threshold", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            {
              id: "doc-1",
              score: 0.9,
              payload: { content: "High score", source: "s1", indexedAt: "2024-01-15T10:00:00Z" },
            },
            {
              id: "doc-2",
              score: 0.5,
              payload: { content: "Low score", source: "s2", indexedAt: "2024-01-14T10:00:00Z" },
            },
            {
              id: "doc-3",
              score: 0.3,
              payload: { content: "Very low", source: "s3", indexedAt: "2024-01-13T10:00:00Z" },
            },
          ],
        })
      );

      const result = await service.retrieve("test query", defaultConfig);

      expect(result.documents).toHaveLength(1);
      expect(result.documents[0]!.id).toBe("doc-1");
      expect(result.allBelowThreshold).toBe(false);
    });

    it("should set allBelowThreshold to true when no documents meet threshold", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            {
              id: "doc-1",
              score: 0.5,
              payload: { content: "Below threshold", source: "s1", indexedAt: "2024-01-15T10:00:00Z" },
            },
            {
              id: "doc-2",
              score: 0.3,
              payload: { content: "Way below", source: "s2", indexedAt: "2024-01-14T10:00:00Z" },
            },
          ],
        })
      );

      const result = await service.retrieve("test query", defaultConfig);

      expect(result.documents).toHaveLength(0);
      expect(result.allBelowThreshold).toBe(true);
    });

    it("should set allBelowThreshold to true when Qdrant returns empty results", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ result: [] })
      );

      const result = await service.retrieve("test query", defaultConfig);

      expect(result.documents).toHaveLength(0);
      expect(result.allBelowThreshold).toBe(true);
    });

    it("should throw timeout error when request exceeds timeout", async () => {
      // Simulate a fetch that takes too long by using abort
      fetchSpy.mockImplementation(
        (_url, options) =>
          new Promise((_resolve, reject) => {
            const signal = (options as RequestInit)?.signal;
            if (signal) {
              signal.addEventListener("abort", () => {
                const error = new Error("The operation was aborted");
                error.name = "AbortError";
                reject(error);
              });
            }
          })
      );

      const shortTimeoutConfig: RetrievalConfig = {
        ...defaultConfig,
        timeoutMs: 50, // Very short timeout for testing
      };

      await expect(
        service.retrieve("slow query", shortTimeoutConfig)
      ).rejects.toThrow(
        "RAG retrieval timed out: Knowledge Store failed to respond within the configured timeout"
      );
    });

    it("should pass the correct query to the embedding service", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ result: [] })
      );

      await service.retrieve("my specific query", defaultConfig);

      expect(fetchSpy).toHaveBeenCalledWith(
        "http://test-embedding:8003/embed",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: "my specific query" }),
        })
      );
    });

    it("should pass the embedding vector and topK limit to Qdrant", async () => {
      const mockEmbedding = [0.1, 0.2, 0.3, 0.4];

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: mockEmbedding })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ result: [] })
      );

      const config: RetrievalConfig = {
        topK: 10,
        relevanceThreshold: 0.8,
        timeoutMs: 10000,
      };

      await service.retrieve("query", config);

      expect(fetchSpy).toHaveBeenCalledWith(
        "http://test-qdrant:6333/collections/test-docs/points/search",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            vector: mockEmbedding,
            limit: 10,
            with_payload: true,
          }),
        })
      );
    });

    it("should throw on embedding service error", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ error: "Internal error" }, 500)
      );

      await expect(
        service.retrieve("query", defaultConfig)
      ).rejects.toThrow("Embedding service error: 500");
    });

    it("should throw on Qdrant search error", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ error: "Collection not found" }, 404)
      );

      await expect(
        service.retrieve("query", defaultConfig)
      ).rejects.toThrow("Qdrant search error: 404");
    });

    it("should include timing metrics in the result", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ result: [] })
      );

      const result = await service.retrieve("query", defaultConfig);

      expect(result.queryEmbeddingTimeMs).toBeGreaterThanOrEqual(0);
      expect(result.searchTimeMs).toBeGreaterThanOrEqual(0);
    });

    it("should correctly map Qdrant payload fields to RetrievedDocument", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            {
              id: "abc-123",
              score: 0.88,
              payload: {
                content: "Important document content",
                source: "manual-upload",
                indexedAt: "2024-03-01T12:30:00Z",
              },
            },
          ],
        })
      );

      const result = await service.retrieve("query", {
        ...defaultConfig,
        relevanceThreshold: 0.5,
      });

      expect(result.documents).toHaveLength(1);
      const doc = result.documents[0]!;
      expect(doc.id).toBe("abc-123");
      expect(doc.content).toBe("Important document content");
      expect(doc.similarityScore).toBe(0.88);
      expect(doc.source).toBe("manual-upload");
      expect(doc.indexedAt).toEqual(new Date("2024-03-01T12:30:00Z"));
    });

    it("should handle missing payload fields gracefully", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            {
              id: "doc-no-payload",
              score: 0.9,
            },
          ],
        })
      );

      const result = await service.retrieve("query", {
        ...defaultConfig,
        relevanceThreshold: 0.5,
      });

      expect(result.documents).toHaveLength(1);
      const doc = result.documents[0]!;
      expect(doc.id).toBe("doc-no-payload");
      expect(doc.content).toBe("");
      expect(doc.source).toBe("unknown");
      expect(doc.indexedAt).toBeInstanceOf(Date);
    });

    it("should respect custom relevance threshold", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            { id: "d1", score: 0.95, payload: { content: "a", source: "s", indexedAt: "2024-01-01T00:00:00Z" } },
            { id: "d2", score: 0.85, payload: { content: "b", source: "s", indexedAt: "2024-01-01T00:00:00Z" } },
            { id: "d3", score: 0.75, payload: { content: "c", source: "s", indexedAt: "2024-01-01T00:00:00Z" } },
          ],
        })
      );

      // Use higher threshold of 0.9
      const result = await service.retrieve("query", {
        topK: 5,
        relevanceThreshold: 0.9,
        timeoutMs: 10000,
      });

      expect(result.documents).toHaveLength(1);
      expect(result.documents[0]!.id).toBe("d1");
    });

    it("should include documents at exactly the threshold value", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1] })
      );

      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          result: [
            { id: "d1", score: 0.7, payload: { content: "exact", source: "s", indexedAt: "2024-01-01T00:00:00Z" } },
            { id: "d2", score: 0.69, payload: { content: "just below", source: "s", indexedAt: "2024-01-01T00:00:00Z" } },
          ],
        })
      );

      const result = await service.retrieve("query", defaultConfig);

      // 0.7 is exactly at threshold (>=), 0.69 is below
      expect(result.documents).toHaveLength(1);
      expect(result.documents[0]!.id).toBe("d1");
    });
  });

  describe("indexDocument()", () => {
    it("should successfully index a text document", async () => {
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        return Promise.resolve(mockFetchResponse({ status: "ok" }));
      });

      const result = await service.indexDocument({
        content: Buffer.from("Hello world this is a test document"),
        format: "text",
        metadata: { title: "Test Doc" },
        sizeMb: 0.001,
      });

      expect(result.success).toBe(true);
      expect(result.documentId).toBeTruthy();
      expect(result.chunksCreated).toBeGreaterThanOrEqual(1);
      expect(result.indexTimeMs).toBeGreaterThanOrEqual(0);
    });

    it("should reject documents over 50MB", async () => {
      const result = await service.indexDocument({
        content: Buffer.from("content"),
        format: "text",
        metadata: {},
        sizeMb: 51,
      });

      expect(result.success).toBe(false);
      expect(result.chunksCreated).toBe(0);
    });

    it("should chunk large documents into multiple pieces", async () => {
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        return Promise.resolve(mockFetchResponse({ status: "ok" }));
      });

      // Create content larger than 2000 chars
      const largeContent = "A".repeat(5000);
      const result = await service.indexDocument({
        content: Buffer.from(largeContent),
        format: "text",
        metadata: {},
        sizeMb: 0.005,
      });

      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBeGreaterThan(1);
    });

    it("should handle HTML format by stripping tags", async () => {
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        return Promise.resolve(mockFetchResponse({ status: "ok" }));
      });

      const html = "<html><body><h1>Title</h1><p>Content here</p></body></html>";
      const result = await service.indexDocument({
        content: Buffer.from(html),
        format: "html",
        metadata: {},
        sizeMb: 0.001,
      });

      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBeGreaterThanOrEqual(1);
    });

    it("should return failure if embedding service fails", async () => {
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ error: "fail" }, 500));

      const result = await service.indexDocument({
        content: Buffer.from("test content"),
        format: "text",
        metadata: {},
        sizeMb: 0.001,
      });

      expect(result.success).toBe(false);
    });
  });

  describe("removeDocument()", () => {
    it("should call Qdrant delete endpoint with document filter", async () => {
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ status: "ok" }));

      await service.removeDocument("doc-123");

      expect(fetchSpy).toHaveBeenCalledWith(
        "http://test-qdrant:6333/collections/test-docs/points/delete",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            filter: {
              must: [{ key: "documentId", match: { value: "doc-123" } }],
            },
          }),
        })
      );
    });

    it("should throw on Qdrant delete error", async () => {
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ error: "fail" }, 500));

      await expect(service.removeDocument("doc-456")).rejects.toThrow(
        "Qdrant delete error: 500"
      );
    });
  });

  describe("constructor defaults", () => {
    it("should use environment variables when no options provided", () => {
      // The service uses defaults internally; just verify it can be constructed
      const defaultService = new RAGPipelineService();
      expect(defaultService).toBeInstanceOf(RAGPipelineService);
    });
  });
});

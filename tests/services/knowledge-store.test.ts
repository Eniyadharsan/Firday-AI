import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { KnowledgeStoreService } from "../../src/services/knowledge-store.js";
import type { KnowledgeItem } from "../../src/interfaces/knowledge-store.js";
import type { DocumentInput } from "../../src/interfaces/rag-pipeline.js";

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

function createTestItem(overrides: Partial<KnowledgeItem> = {}): KnowledgeItem {
  return {
    id: "",
    type: "fact",
    content: "Test content",
    createdAt: new Date(),
    metadata: {},
    ...overrides,
  };
}

describe("KnowledgeStoreService", () => {
  let service: KnowledgeStoreService;
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    service = new KnowledgeStoreService({
      embeddingUrl: "http://test-embedding:8003",
      qdrantUrl: "http://test-qdrant:6333",
      collectionName: "test-docs",
    });
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("storeItem()", () => {
    it("should store an item and return a valid UUID", async () => {
      const item = createTestItem({ content: "My preference" });
      const itemId = await service.storeItem("user-1", item);

      expect(itemId).toBeTruthy();
      expect(typeof itemId).toBe("string");
      // UUID format check
      expect(itemId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
      );
    });

    it("should store multiple items for the same user", async () => {
      await service.storeItem("user-1", createTestItem({ content: "Item 1" }));
      await service.storeItem("user-1", createTestItem({ content: "Item 2" }));
      await service.storeItem("user-1", createTestItem({ content: "Item 3" }));

      const count = await service.getItemCount("user-1");
      expect(count).toBe(3);
    });

    it("should isolate items between different users", async () => {
      await service.storeItem("user-1", createTestItem({ content: "User 1 item" }));
      await service.storeItem("user-2", createTestItem({ content: "User 2 item" }));

      expect(await service.getItemCount("user-1")).toBe(1);
      expect(await service.getItemCount("user-2")).toBe(1);
    });

    it("should reject storage when user reaches 500-item capacity", async () => {
      // Store 500 items
      for (let i = 0; i < 500; i++) {
        await service.storeItem("user-full", createTestItem({ content: `Item ${i}` }));
      }

      // Attempt to store item 501
      await expect(
        service.storeItem("user-full", createTestItem({ content: "One too many" }))
      ).rejects.toThrow("Knowledge Store capacity exceeded");
    });

    it("should store items of different types", async () => {
      await service.storeItem("user-1", createTestItem({ type: "preference", content: "I like TypeScript" }));
      await service.storeItem("user-1", createTestItem({ type: "fact", content: "Earth orbits the Sun" }));
      await service.storeItem("user-1", createTestItem({ type: "document", content: "My doc content" }));

      const items = await service.getItems("user-1");
      expect(items).toHaveLength(3);
      expect(items.map((i) => i.type).sort()).toEqual(["document", "fact", "preference"]);
    });

    it("should assign createdAt date to stored items", async () => {
      const before = new Date();
      const itemId = await service.storeItem("user-1", createTestItem());
      const after = new Date();

      const items = await service.getItems("user-1");
      const stored = items.find((i) => i.id === itemId);
      expect(stored).toBeDefined();
      expect(stored!.createdAt.getTime()).toBeGreaterThanOrEqual(before.getTime());
      expect(stored!.createdAt.getTime()).toBeLessThanOrEqual(after.getTime());
    });
  });

  describe("removeItem()", () => {
    it("should remove an existing item", async () => {
      const itemId = await service.storeItem("user-1", createTestItem());
      expect(await service.getItemCount("user-1")).toBe(1);

      await service.removeItem("user-1", itemId);
      expect(await service.getItemCount("user-1")).toBe(0);
    });

    it("should throw when removing a non-existent item", async () => {
      await expect(
        service.removeItem("user-1", "non-existent-id")
      ).rejects.toThrow("Item not found");
    });

    it("should throw when removing from a user with no items", async () => {
      await expect(
        service.removeItem("no-items-user", "some-id")
      ).rejects.toThrow("Item not found");
    });

    it("should allow storing new items after removal frees capacity", async () => {
      // Fill to capacity
      const ids: string[] = [];
      for (let i = 0; i < 500; i++) {
        ids.push(await service.storeItem("user-1", createTestItem({ content: `Item ${i}` })));
      }

      // Remove one
      await service.removeItem("user-1", ids[0]!);

      // Now we can store a new item
      const newId = await service.storeItem("user-1", createTestItem({ content: "New item" }));
      expect(newId).toBeTruthy();
      expect(await service.getItemCount("user-1")).toBe(500);
    });
  });

  describe("getItems()", () => {
    it("should return empty array for user with no items", async () => {
      const items = await service.getItems("empty-user");
      expect(items).toEqual([]);
    });

    it("should return all stored items for a user", async () => {
      await service.storeItem("user-1", createTestItem({ content: "A" }));
      await service.storeItem("user-1", createTestItem({ content: "B" }));

      const items = await service.getItems("user-1");
      expect(items).toHaveLength(2);
      expect(items.map((i) => i.content)).toContain("A");
      expect(items.map((i) => i.content)).toContain("B");
    });
  });

  describe("getItemCount()", () => {
    it("should return 0 for user with no items", async () => {
      expect(await service.getItemCount("new-user")).toBe(0);
    });

    it("should accurately track item count", async () => {
      await service.storeItem("user-1", createTestItem());
      expect(await service.getItemCount("user-1")).toBe(1);

      await service.storeItem("user-1", createTestItem());
      expect(await service.getItemCount("user-1")).toBe(2);
    });

    it("should decrease after removal", async () => {
      const id = await service.storeItem("user-1", createTestItem());
      await service.storeItem("user-1", createTestItem());
      expect(await service.getItemCount("user-1")).toBe(2);

      await service.removeItem("user-1", id);
      expect(await service.getItemCount("user-1")).toBe(1);
    });
  });

  describe("indexDocument()", () => {
    it("should reject documents exceeding 50MB", async () => {
      const document: DocumentInput = {
        content: Buffer.from("some content"),
        format: "text",
        metadata: { title: "Large doc" },
        sizeMb: 51,
      };

      const result = await service.indexDocument(document);

      expect(result.success).toBe(false);
      expect(result.chunksCreated).toBe(0);
      expect(result.documentId).toBeTruthy();
    });

    it("should successfully index a small text document", async () => {
      // Mock embedding response
      fetchSpy.mockResolvedValue(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );
      // The last call will be the Qdrant upsert
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ status: "ok" })
      );

      const document: DocumentInput = {
        content: Buffer.from("Hello world, this is a test document."),
        format: "text",
        metadata: { title: "Test" },
        sizeMb: 0.001,
      };

      const result = await service.indexDocument(document);

      expect(result.success).toBe(true);
      expect(result.documentId).toBeTruthy();
      expect(result.chunksCreated).toBeGreaterThanOrEqual(1);
      expect(result.indexTimeMs).toBeGreaterThanOrEqual(0);
    });

    it("should index HTML documents by stripping tags", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ status: "ok" })
      );

      const html = "<html><body><p>Hello world</p><script>alert('x')</script></body></html>";
      const document: DocumentInput = {
        content: Buffer.from(html),
        format: "html",
        metadata: {},
        sizeMb: 0.001,
      };

      const result = await service.indexDocument(document);
      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBeGreaterThanOrEqual(1);
    });

    it("should index PDF documents by extracting text", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ embedding: [0.1, 0.2, 0.3] })
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ status: "ok" })
      );

      // Simulate simple PDF-like content with parenthesized text
      const pdfContent = "%PDF-1.4 (Hello from PDF) (This is content)";
      const document: DocumentInput = {
        content: Buffer.from(pdfContent),
        format: "pdf",
        metadata: {},
        sizeMb: 0.001,
      };

      const result = await service.indexDocument(document);
      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBeGreaterThanOrEqual(1);
    });

    it("should create multiple chunks for large documents", async () => {
      // Create a document larger than chunk size (~2000 chars)
      const largeContent = "This is a sentence. ".repeat(300); // ~6000 chars

      // Multiple embedding calls + 1 Qdrant call
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        return Promise.resolve(mockFetchResponse({ status: "ok" }));
      });

      const document: DocumentInput = {
        content: Buffer.from(largeContent),
        format: "text",
        metadata: {},
        sizeMb: 0.006,
      };

      const result = await service.indexDocument(document);
      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBeGreaterThan(1);
    });

    it("should return failure when embedding service errors", async () => {
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ error: "Service unavailable" }, 503)
      );

      const document: DocumentInput = {
        content: Buffer.from("Some content"),
        format: "text",
        metadata: {},
        sizeMb: 0.001,
      };

      const result = await service.indexDocument(document);
      expect(result.success).toBe(false);
    });

    it("should return failure when Qdrant storage errors", async () => {
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        // Qdrant fails
        return Promise.resolve(mockFetchResponse({ error: "Storage error" }, 500));
      });

      const document: DocumentInput = {
        content: Buffer.from("Some content"),
        format: "text",
        metadata: {},
        sizeMb: 0.001,
      };

      const result = await service.indexDocument(document);
      expect(result.success).toBe(false);
    });

    it("should include document metadata in Qdrant upsert", async () => {
      fetchSpy.mockImplementation((url) => {
        const urlStr = typeof url === "string" ? url : (url as Request).url;
        if (urlStr.includes("/embed")) {
          return Promise.resolve(mockFetchResponse({ embedding: [0.1, 0.2, 0.3] }));
        }
        return Promise.resolve(mockFetchResponse({ status: "ok" }));
      });

      const document: DocumentInput = {
        content: Buffer.from("Document content"),
        format: "text",
        metadata: { title: "My Doc", author: "Test" },
        sizeMb: 0.001,
      };

      await service.indexDocument(document);

      // Check the Qdrant upsert call
      const qdrantCall = fetchSpy.mock.calls.find(
        (call) => typeof call[0] === "string" && call[0].includes("/points")
      );
      expect(qdrantCall).toBeDefined();

      const body = JSON.parse(qdrantCall![1]!.body as string);
      expect(body.points[0].payload.title).toBe("My Doc");
      expect(body.points[0].payload.author).toBe("Test");
      expect(body.points[0].payload.documentId).toBeTruthy();
      expect(body.points[0].payload.chunkIndex).toBe(0);
      expect(body.points[0].payload.indexedAt).toBeTruthy();
    });

    it("should handle empty document content", async () => {
      const document: DocumentInput = {
        content: Buffer.from(""),
        format: "text",
        metadata: {},
        sizeMb: 0,
      };

      // No fetch calls should be made for empty content (no chunks)
      const result = await service.indexDocument(document);
      expect(result.success).toBe(true);
      expect(result.chunksCreated).toBe(0);
    });
  });

  describe("constructor", () => {
    it("should use defaults when no options provided", () => {
      const defaultService = new KnowledgeStoreService();
      expect(defaultService).toBeInstanceOf(KnowledgeStoreService);
    });

    it("should use provided options", () => {
      const customService = new KnowledgeStoreService({
        embeddingUrl: "http://custom:9000",
        qdrantUrl: "http://custom:7333",
        collectionName: "custom-collection",
      });
      expect(customService).toBeInstanceOf(KnowledgeStoreService);
    });
  });
});

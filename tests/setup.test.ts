import { describe, it, expect } from "vitest";

describe("Project Setup", () => {
  it("should have a valid test environment", () => {
    expect(true).toBe(true);
  });

  it("should support ES2022 features", () => {
    // Array.at()
    const arr = [1, 2, 3];
    expect(arr.at(-1)).toBe(3);

    // Object.hasOwn()
    const obj = { key: "value" };
    expect(Object.hasOwn(obj, "key")).toBe(true);
  });
});

/**
 * What a tile may say about where its data came from: the datasets the server
 * said the statement read, and nothing else.
 */
import { describe, expect, it } from "vitest";

import { queryScope } from "@/lib/widgets/provenance";

describe("query scope", () => {
  it("reports the datasets the server said were read", () => {
    expect(queryScope(["projects", "tasks"])).toEqual([
      { key: "projects", label: "projects" },
      { key: "tasks", label: "tasks" },
    ]);
  });

  it("reports nothing for a statement that read nothing", () => {
    expect(queryScope([])).toEqual([]);
  });
});

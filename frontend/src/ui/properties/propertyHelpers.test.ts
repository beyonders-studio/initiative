import { describe, expect, it } from "vitest";

import { buildPropertySummary } from "@/__tests__/factories";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";

import { userReferenceValue } from "./propertyHelpers";

describe("a person a property holds", () => {
  const holding = (value: unknown) =>
    userReferenceValue(buildPropertySummary({ type: MetadataType.user_reference, value }));

  it("reads a person drawn with their details, or named by id or reference alone", () => {
    expect(holding({ id: 3, full_name: "Grace" })).toEqual({ id: 3, full_name: "Grace" });
    expect(holding("p-grace")).toEqual({ id: "p-grace" });
    expect(holding(3)).toEqual({ id: 3 });
  });

  it("reads nobody from an empty value or another type's", () => {
    expect(holding(null)).toBeNull();
    expect(
      userReferenceValue(buildPropertySummary({ type: MetadataType.text, value: "p-grace" }))
    ).toBeNull();
  });
});

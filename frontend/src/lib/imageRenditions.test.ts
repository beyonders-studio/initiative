import { describe, expect, it } from "vitest";

import { ImageRenditionError, MAX_SOURCE_BYTES, renderCommunityIcon } from "./imageRenditions";

const file = (bytes: number, type: string) =>
  new File([new Uint8Array(bytes)], "pick.bin", { type });

describe("renderCommunityIcon", () => {
  it("refuses a file that is not an image before reading any of it", async () => {
    await expect(renderCommunityIcon(file(16, "application/pdf"))).rejects.toThrow(
      ImageRenditionError
    );
    await expect(renderCommunityIcon(file(16, "application/pdf"))).rejects.toMatchObject({
      code: "notAnImage",
    });
  });

  it("refuses a source too large to work with, before decoding it", async () => {
    await expect(
      renderCommunityIcon(file(MAX_SOURCE_BYTES + 1, "image/png"))
    ).rejects.toMatchObject({
      code: "tooLarge",
    });
  });
});

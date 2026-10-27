import { PenTool, ScrollText, Sheet } from "lucide-react";
import { describe, expect, it } from "vitest";

import { fileIcon } from "@/lib/fileIcon";

describe("fileIcon", () => {
  it("draws a spreadsheet as a sheet, not as prose", () => {
    // The relations card used to give every file the default scroll, which
    // said nothing about which of them was which.
    const { Icon, colorClass } = fileIcon({ file_type: "sheet" });
    expect(Icon).toBe(Sheet);
    expect(colorClass).toBe("text-emerald-500");
  });

  it("draws a whiteboard as a pen", () => {
    expect(fileIcon({ file_type: "excalidraw" }).Icon).toBe(PenTool);
  });

  it("draws an ordinary file as a scroll", () => {
    expect(fileIcon({ file_type: "lexical" }).Icon).toBe(ScrollText);
  });

  it("draws a file by its format rather than by being a file", () => {
    const pdf = fileIcon({ file_type: "pdf" });
    const image = fileIcon({ file_type: "png" });
    expect(pdf.Icon).not.toBe(ScrollText);
    expect(image.Icon).not.toBe(pdf.Icon);
  });

  it("uses a recognised provider's own mark for a smart link", () => {
    const figma = fileIcon({
      file_type: "url",
      smart_link_url: "https://www.figma.com/file/abc",
    });
    expect(figma.Icon).not.toBe(ScrollText);
  });

  it("falls back rather than failing on a smart link with no url", () => {
    expect(fileIcon({ file_type: "url" }).Icon).toBe(ScrollText);
  });

  it("survives a row that says nothing about itself", () => {
    expect(fileIcon({}).Icon).toBe(ScrollText);
  });
});

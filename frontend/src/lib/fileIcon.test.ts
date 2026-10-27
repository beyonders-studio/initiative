import { FileArchive, FileText, Palette, PenTool, ScrollText, Sheet } from "lucide-react";
import { describe, expect, it } from "vitest";

import { FileKind, FileType } from "@/api/generated/initiativeAPI.schemas";
import { fileIcon } from "@/lib/fileIcon";
import { FILE_TYPE_KINDS } from "@/lib/fileTypes";

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

  it("draws a format by its category", () => {
    expect(fileIcon({ file_type: "zip" }).Icon).toBe(FileArchive);
    expect(fileIcon({ file_type: "psd" }).Icon).toBe(Palette);
    expect(fileIcon({ file_type: "ai" }).Icon).toBe(Palette);
  });

  it("gives every category but the plain one a mark of its own", () => {
    const plain: FileKind[] = [FileKind.text, FileKind.link, FileKind.other];
    const marked = Object.values(FileType).filter(
      (type) => !plain.includes(FILE_TYPE_KINDS[type]) && type !== FileType.lexical
    );
    for (const type of marked) {
      expect(fileIcon({ file_type: type }).colorClass, type).not.toBe("text-muted-foreground");
    }
    // The generic page is left to text and to nothing in particular.
    expect(fileIcon({ file_type: "other" }).Icon).toBe(FileText);
  });

  it("survives a row that says nothing about itself", () => {
    expect(fileIcon({}).Icon).toBe(ScrollText);
  });
});

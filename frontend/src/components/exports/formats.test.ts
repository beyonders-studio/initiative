import { describe, expect, it } from "vitest";

import { FileType } from "@/api/generated/initiativeAPI.schemas";

import exports from "../../../public/locales/en/exports.json";
import {
  fileSelectionFormats,
  fileTypeFormats,
  REPORT_FILE_FORMATS,
  REPORT_TOOL_FORMATS,
  TOOL_EXPORT_FORMATS,
} from "./formats";

describe("fileSelectionFormats", () => {
  // A mixed selection intersects its types' formats; smart links share md and
  // the json envelope with text files, whiteboards and spreadsheets share json.
  it.each([
    [
      ["lexical", "lexical"],
      ["pdf", "md", "docx", "json"],
    ],
    [["lexical", "sheet"], ["json"]],
    [["lexical", "pdf"], []],
    [[], []],
    [["excalidraw", "sheet"], ["json"]],
    [["url"], ["md", "json"]],
    [
      ["lexical", "url"],
      ["md", "json"],
    ],
  ] as [FileType[], string[]][])("offers %j the formats %j", (types, expected) => {
    expect(fileSelectionFormats(types).map((f) => f.format)).toEqual(expected);
  });

  it("labels json the same for a single-type selection and a mixed one", () => {
    expect(fileSelectionFormats(["lexical"]).find((f) => f.format === "json")?.labelKey).toBe(
      "export.formatJson"
    );
    expect(fileSelectionFormats(["lexical", "sheet"])[0].labelKey).toBe("export.formatJson");
  });
});

describe("format labels", () => {
  // Every export surface translates these keys in the ``exports`` namespace.
  // A key that resolves nowhere renders as the raw ``export.formatPdf``, which
  // is what the community export wizard showed while it looked them up under
  // ``tasks`` after they had moved.
  const lists = [
    ...Object.values(FileType).map(fileTypeFormats),
    ...Object.values(TOOL_EXPORT_FORMATS),
    ...Object.values(REPORT_TOOL_FORMATS),
    ...Object.values(REPORT_FILE_FORMATS),
  ];
  const labelKeys = [...new Set(lists.flatMap((list) => (list ?? []).map((o) => o.labelKey)))];

  it.each(labelKeys)("%s has English wording in exports.json", (labelKey) => {
    const value = labelKey
      .split(".")
      .reduce<unknown>(
        (node, part) => (node as Record<string, unknown> | undefined)?.[part],
        exports
      );
    expect(typeof value).toBe("string");
  });
});

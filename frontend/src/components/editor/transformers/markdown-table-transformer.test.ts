import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import {
  $isTableCellNode,
  $isTableNode,
  TableCellNode,
  TableNode,
  TableRowNode,
} from "@lexical/table";
import { $getRoot, defineExtension, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { TABLE } from "@/components/editor/transformers/markdown-table-transformer";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/table-markdown",
      dependencies: [RichTextExtension],
      nodes: [TableNode, TableRowNode, TableCellNode],
      onError: (error) => {
        throw error;
      },
    })
  );
}

/** Each cell of the table as `text:colspan:rowspan`, row by row. */
function cellsOf(editor: LexicalEditor): string[][] {
  let rows: string[][] = [];
  editor.getEditorState().read(() => {
    const table = $getRoot().getFirstChild();
    if (!$isTableNode(table)) throw new Error("no table");
    rows = table.getChildren().map((row) =>
      (row as TableRowNode)
        .getChildren()
        .filter($isTableCellNode)
        .map((cell) => `${cell.getTextContent()}:${cell.getColSpan()}:${cell.getRowSpan()}`)
    );
  });
  return rows;
}

const MERGED = ["| Name | Detail ||", "| --- | --- | --- |", "| Tall | a | b |", "| ^^ | c | d |"];

describe("tables in markdown", () => {
  it("read MultiMarkdown's merged cells", () => {
    const editor = makeEditor();
    editor.update(() => $convertFromMarkdownString(MERGED.join("\n"), [TABLE]), {
      discrete: true,
    });
    expect(cellsOf(editor)).toEqual([
      ["Name:1:1", "Detail:2:1"],
      ["Tall:1:2", "a:1:1", "b:1:1"],
      ["c:1:1", "d:1:1"],
    ]);
  });

  it("write them back the same way", () => {
    const editor = makeEditor();
    let exported = "";
    editor.update(() => $convertFromMarkdownString(MERGED.join("\n"), [TABLE]), {
      discrete: true,
    });
    editor.getEditorState().read(() => {
      exported = $convertToMarkdownString([TABLE]);
    });
    expect(exported.split("\n")).toEqual(MERGED);
  });

  it("leave a table without merges as it always was", () => {
    const editor = makeEditor();
    const plain = ["| a | b |", "| --- | --- |", "| c |  |"];
    let exported = "";
    editor.update(() => $convertFromMarkdownString(plain.join("\n"), [TABLE]), {
      discrete: true,
    });
    editor.getEditorState().read(() => {
      exported = $convertToMarkdownString([TABLE]);
    });
    expect(cellsOf(editor)).toEqual([
      ["a:1:1", "b:1:1"],
      ["c:1:1", ":1:1"],
    ]);
    expect(exported.split("\n")).toEqual(plain);
  });

  it("keep a pipe inside a cell, written the way GFM escapes it", () => {
    const editor = makeEditor();
    const piped = ["| either \\| or | b |", "| --- | --- |"];
    let exported = "";
    editor.update(() => $convertFromMarkdownString(piped.join("\n"), [TABLE]), {
      discrete: true,
    });
    editor.getEditorState().read(() => {
      exported = $convertToMarkdownString([TABLE]);
    });
    expect(cellsOf(editor)).toEqual([["either | or:1:1", "b:1:1"]]);
    expect(exported.split("\n")).toEqual(piped);
  });
});

import { buildEditorFromExtensions } from "@lexical/extension";
import { $isLinkNode } from "@lexical/link";
import { $getRoot, $isElementNode, type LexicalNode } from "lexical";
import { describe, expect, it } from "vitest";

import { documentExtension } from "@/components/editor/document-extension";
import { $isImageNode } from "@/components/editor/nodes/image-node";
import type { ReceivedShare } from "@/lib/share/pendingShare";
import { asTitle, shareBody, shareMarkdown, shareNote, shareTitle } from "@/lib/share/shareContent";

const share = (overrides: Partial<ReceivedShare> = {}): ReceivedShare => ({
  id: 1,
  title: "",
  texts: [],
  files: [],
  opened: false,
  ...overrides,
});

describe("asTitle", () => {
  it("drops the characters a name may not carry", () => {
    expect(asTitle("@moss on #launch day")).toBe("moss on launch day");
  });

  it("keeps a title to one line", () => {
    expect(asTitle("  first\n\tsecond  ")).toBe("first second");
  });

  it("holds a title to the most a title may be", () => {
    expect(asTitle("x".repeat(300))).toHaveLength(255);
  });
});

describe("shareTitle", () => {
  it("takes the title the other app gave", () => {
    expect(
      shareTitle(share({ title: "A page", texts: ["https://example.com/a"] }), "fallback")
    ).toBe("A page");
  });

  it("takes the first written line when there is no title", () => {
    expect(
      shareTitle(share({ texts: ["https://example.com/a\nBuy milk\nand eggs"] }), "fallback")
    ).toBe("Buy milk");
  });

  it("names a bare link by its site", () => {
    expect(shareTitle(share({ texts: ["https://www.example.com/a/b?c=d"] }), "fallback")).toBe(
      "example.com"
    );
  });

  it("falls back for a share that is only pictures", () => {
    expect(
      shareTitle(
        share({ files: [{ uri: "/p.jpg", name: "p.jpg", mimeType: "image/jpeg" }] }),
        "Shared picture"
      )
    ).toBe("Shared picture");
  });

  it("passes over a title that is nothing but sigils", () => {
    expect(shareTitle(share({ title: "#@", texts: ["Real words"] }), "fallback")).toBe(
      "Real words"
    );
  });
});

describe("shareNote", () => {
  it("keeps everything written, a paragraph each", () => {
    expect(shareNote(share({ texts: ["one", "two"] }), "Title")).toBe("one\n\ntwo");
  });

  it("leaves out a note that only repeats the title", () => {
    expect(shareNote(share({ texts: ["Buy milk"] }), "Buy milk")).toBe("");
  });

  it("keeps a note the title had to strip of a sigil", () => {
    const shared = share({ texts: ["Meet @bob at #3"] });
    expect(shareNote(shared, shareTitle(shared, "fallback"))).toBe("Meet @bob at #3");
  });

  it("keeps a note too long to be a title", () => {
    const long = "word ".repeat(80).trim();
    const shared = share({ texts: [long] });
    expect(shareNote(shared, shareTitle(shared, "fallback"))).toBe(long);
  });
});

describe("shareMarkdown", () => {
  it("puts each picture below the note", () => {
    expect(shareMarkdown("Look at this", [{ name: "cat.jpg", url: "/uploads/1/cat.jpg" }])).toBe(
      "Look at this\n\n![cat](/uploads/1/cat.jpg)"
    );
  });

  it("is empty for an empty share", () => {
    expect(shareMarkdown("  ", [])).toBe("");
  });
});

/** The top-level blocks of a state, as the document editor reads it back. */
function readInDocumentEditor(state: ReturnType<typeof shareBody>) {
  const editor = buildEditorFromExtensions(
    documentExtension({
      collaborative: false,
      editable: false,
      initialEditorState: JSON.stringify(state),
      onError: (error) => {
        throw error;
      },
    })
  );
  const describe = (node: LexicalNode): unknown => {
    if ($isImageNode(node)) return { image: node.getSrc(), alt: node.getAltText() };
    if ($isLinkNode(node)) return { link: node.getURL(), text: node.getTextContent() };
    if ($isElementNode(node)) return node.getChildren().map(describe);
    return node.getTextContent();
  };
  return editor.getEditorState().read(() => $getRoot().getChildren().map(describe));
}

describe("shareBody", () => {
  it("is a state the document editor opens, links live and pictures in place", () => {
    const state = shareBody("Read this: https://example.com/a.\nSecond line", [
      { src: "/uploads/1/cat.jpg", altText: "cat" },
    ]);

    expect(readInDocumentEditor(state)).toEqual([
      ["Read this: ", { link: "https://example.com/a", text: "https://example.com/a" }, "."],
      ["Second line"],
      [{ image: "/uploads/1/cat.jpg", alt: "cat" }],
    ]);
  });

  it("is one empty paragraph for a share with nothing in it", () => {
    expect(readInDocumentEditor(shareBody("", []))).toEqual([[]]);
  });
});

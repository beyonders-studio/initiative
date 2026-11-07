import { buildEditorFromExtensions } from "@lexical/extension";
import {
  $createLinkNode,
  $isAutoLinkNode,
  $isLinkNode,
  AutoLinkNode,
  LinkExtension,
} from "@lexical/link";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  defineExtension,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { LinkSanitizeExtension } from "./link-sanitize-extension";

function makeEditor() {
  return buildEditorFromExtensions({
    name: "test",
    // The autolink node alone: AutoLinkExtension's matching would unlink the
    // test link's text before the check reads it.
    dependencies: [
      LinkExtension,
      defineExtension({ name: "test/autolink-node", nodes: [AutoLinkNode] }),
      LinkSanitizeExtension,
    ],
    onError: (e) => {
      throw e;
    },
  });
}

/**
 * Builds a serialized Lexical document containing a single link with the given
 * URL, matching the SerializedLinkNode shape produced by the editor.
 */
function buildLinkDocument(url: string, type: "link" | "autolink" = "link") {
  return {
    root: {
      children: [
        {
          children: [
            {
              type,
              version: 1,
              url,
              rel: "noopener noreferrer",
              target: "_blank",
              title: null,
              ...(type === "autolink" ? { isUnlinked: false } : {}),
              children: [
                {
                  type: "text",
                  version: 1,
                  text: "click me",
                  detail: 0,
                  format: 0,
                  mode: "normal",
                  style: "",
                },
              ],
              direction: "ltr" as const,
              format: "" as const,
              indent: 0,
            },
          ],
          type: "paragraph",
          version: 1,
          direction: "ltr" as const,
          format: "" as const,
          indent: 0,
        },
      ],
      type: "root",
      version: 1,
      direction: "ltr" as const,
      format: "" as const,
      indent: 0,
    },
  };
}

/** Loads a serialized document the way a stored one is loaded, then returns the link URL. */
async function importAndReadLinkUrl(
  editor: LexicalEditor,
  serialized: object
): Promise<{ storedUrl: string | null; renderedHref: string | null }> {
  editor.setEditorState(editor.parseEditorState(JSON.stringify(serialized)));

  let storedUrl: string | null = null;
  let renderedHref: string | null = null;
  editor.getEditorState().read(() => {
    const link = $getRoot()
      .getAllTextNodes()
      .map((n) => n.getParent())
      .find((p) => $isLinkNode(p) || $isAutoLinkNode(p));
    if (link && ($isLinkNode(link) || $isAutoLinkNode(link))) {
      storedUrl = link.getURL();
      // sanitizeUrl is the render-time neutralization Lexical applies in createDOM.
      renderedHref = link.sanitizeUrl(link.getURL());
    }
  });
  return { storedUrl, renderedHref };
}

describe("LinkSanitizeExtension", () => {
  it("neutralizes a stored javascript: link on import", async () => {
    const editor = makeEditor();
    const { storedUrl, renderedHref } = await importAndReadLinkUrl(
      editor,
      buildLinkDocument("javascript:alert(document.domain)")
    );
    expect(storedUrl).toBe("about:blank");
    expect(renderedHref).toBe("about:blank");
  });

  it("neutralizes a stored data: link on import", async () => {
    const editor = makeEditor();
    const { storedUrl } = await importAndReadLinkUrl(
      editor,
      buildLinkDocument("data:text/html,<script>alert(1)</script>")
    );
    expect(storedUrl).toBe("about:blank");
  });

  it("neutralizes a javascript: AutoLinkNode on import", async () => {
    const editor = makeEditor();
    const { storedUrl } = await importAndReadLinkUrl(
      editor,
      buildLinkDocument("javascript:alert(1)", "autolink")
    );
    expect(storedUrl).toBe("about:blank");
  });

  it("leaves an https link untouched", async () => {
    const editor = makeEditor();
    const { storedUrl, renderedHref } = await importAndReadLinkUrl(
      editor,
      buildLinkDocument("https://example.com/safe")
    );
    expect(storedUrl).toBe("https://example.com/safe");
    expect(renderedHref).toBe("https://example.com/safe");
  });

  it("leaves a mailto link untouched", async () => {
    const editor = makeEditor();
    const { storedUrl } = await importAndReadLinkUrl(
      editor,
      buildLinkDocument("mailto:user@example.com")
    );
    expect(storedUrl).toBe("mailto:user@example.com");
  });

  it("neutralizes a javascript: URL applied programmatically (paste/edit path)", async () => {
    const editor = makeEditor();
    await new Promise<void>((resolve) => {
      editor.update(
        () => {
          const paragraph = $createParagraphNode();
          const link = $createLinkNode("javascript:alert(1)");
          link.append($createTextNode("evil"));
          paragraph.append(link);
          $getRoot().clear().append(paragraph);
        },
        { onUpdate: resolve }
      );
    });

    let storedUrl: string | null = null;
    editor.getEditorState().read(() => {
      const link = $getRoot()
        .getAllTextNodes()
        .map((n) => n.getParent())
        .find((p) => $isLinkNode(p) || $isAutoLinkNode(p));
      if (link && ($isLinkNode(link) || $isAutoLinkNode(link))) {
        storedUrl = link.getURL();
      }
    });
    expect(storedUrl).toBe("about:blank");
  });
});

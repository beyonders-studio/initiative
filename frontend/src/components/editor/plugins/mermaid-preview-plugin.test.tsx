import { $createCodeNode } from "@lexical/code";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { waitFor } from "@testing-library/react";
import { $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { useMemo } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/components/editor/document-extension";
import { Plugins } from "@/components/editor/plugins";
import { TooltipProvider } from "@/ui/tooltip";

const render = vi.fn(async (_id: string, source: string) => {
  if (source.includes("broken")) {
    throw new Error("Parse error on line 1:\nmore detail");
  }
  return { svg: "<svg xmlns='http://www.w3.org/2000/svg'></svg>" };
});

vi.mock("mermaid", () => ({ default: { initialize: vi.fn(), render } }));

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

function Harness({ readOnly }: { readOnly: boolean }) {
  const extension = useMemo(
    () => documentExtension({ collaborative: false, editable: !readOnly }),
    [readOnly]
  );
  return (
    <LexicalExtensionComposer extension={extension} contentEditable={null}>
      <TooltipProvider>
        <Grab />
        <Plugins showToolbar={false} readOnly={readOnly} />
      </TooltipProvider>
    </LexicalExtensionComposer>
  );
}

function writeCode(language: string, text: string) {
  editor.update(
    () => {
      $getRoot()
        .clear()
        .append($createCodeNode(language).append($createTextNode(text)));
    },
    { discrete: true }
  );
}

describe("a Mermaid code block", () => {
  beforeEach(() => {
    render.mockClear();
    URL.createObjectURL = vi.fn(() => "blob:diagram");
    URL.revokeObjectURL = vi.fn();
  });

  it("is drawn as its diagram, under the code", async () => {
    const { container } = renderPage(() => <Harness readOnly={false} />);
    await waitFor(() => expect(editor).toBeTruthy());
    writeCode("mermaid", "flowchart LR\n  A --> B");

    await waitFor(() => expect(container.querySelector(".mermaid-preview img")).not.toBeNull());
    const code = container.querySelector("code");
    expect(code?.nextElementSibling?.classList.contains("mermaid-preview")).toBe(true);
    expect(code?.getAttribute("data-mermaid-drawn")).toBe("true");
    expect(render.mock.calls[0][1]).toBe("flowchart LR\n  A --> B");
  });

  it("says what is wrong with a diagram that will not draw", async () => {
    const { container } = renderPage(() => <Harness readOnly={false} />);
    await waitFor(() => expect(editor).toBeTruthy());
    writeCode("mermaid", "broken");

    await waitFor(() =>
      expect(container.querySelector(".mermaid-preview-error")?.textContent).toContain(
        "Parse error on line 1:"
      )
    );
    expect(container.querySelector("code")?.hasAttribute("data-mermaid-drawn")).toBe(false);
  });

  it("leaves other code alone, and takes its picture away when it stops being Mermaid", async () => {
    const { container } = renderPage(() => <Harness readOnly={false} />);
    await waitFor(() => expect(editor).toBeTruthy());
    writeCode("javascript", "const a = 1;");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(container.querySelector(".mermaid-preview")).toBeNull();

    writeCode("mermaid", "flowchart LR\n  A --> B");
    await waitFor(() => expect(container.querySelector(".mermaid-preview")).not.toBeNull());
    editor.update(
      () => {
        const code = $getRoot().getFirstChild();
        if (code && "setLanguage" in code) {
          (code as ReturnType<typeof $createCodeNode>).setLanguage("javascript");
        }
      },
      { discrete: true }
    );
    await waitFor(() => expect(container.querySelector(".mermaid-preview")).toBeNull());
  });

  it("keeps its language through markdown's fence", async () => {
    const { $convertFromMarkdownString } = await import("@lexical/markdown");
    const { markdownTransformers } = await import(
      "@/components/editor/extensions/markdown-shortcuts-extension"
    );
    renderPage(() => <Harness readOnly={false} />);
    await waitFor(() => expect(editor).toBeTruthy());
    editor.update(
      () =>
        $convertFromMarkdownString(
          "```mermaid\nflowchart LR\n  A --> B\n```",
          markdownTransformers([])
        ),
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      const code = $getRoot().getFirstChild() as ReturnType<typeof $createCodeNode>;
      expect(code.getLanguage()).toBe("mermaid");
    });
  });
});

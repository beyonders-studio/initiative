import { $isCodeNode, CodeNode } from "@lexical/code";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { mergeRegister } from "@lexical/utils";
import { $getNodeByKey, type LexicalEditor, type NodeKey, setDOMUnmanaged } from "lexical";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useTheme } from "@/hooks/useTheme";

/** The language a code block names to be drawn as a diagram. */
export const MERMAID_LANGUAGE = "mermaid";

/** How long typing has to pause before the diagram is redrawn. */
const REDRAW_DELAY_MS = 400;

type MermaidApi = typeof import("mermaid").default;

let mermaidPromise: Promise<MermaidApi> | null = null;
let renderCount = 0;

/** Mermaid, loaded the first time a page has a diagram to draw. It is large,
 * and most documents never need it. */
function loadMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
}

interface Preview {
  element: HTMLDivElement;
  source: string;
  timer: ReturnType<typeof setTimeout> | null;
  url: string | null;
}

/**
 * Draws every code block written in Mermaid as its diagram, just below the
 * code. The block stays an ordinary code block — in the document, in
 * markdown (a `mermaid` fence), in exports — and the picture is the editor's
 * own decoration beside it, never part of what is saved.
 *
 * On a page being read rather than edited the code steps aside once the
 * diagram has drawn, so a reader sees the picture; while editing both show.
 *
 * The diagram is shown as an image: Mermaid draws it strictly, and as a
 * picture nothing in it can do more than be looked at.
 */
export function MermaidPreviewPlugin() {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("editor");
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const previews = new Map<NodeKey, Preview>();

    const discard = (key: NodeKey) => {
      const preview = previews.get(key);
      if (!preview) return;
      if (preview.timer) clearTimeout(preview.timer);
      if (preview.url) URL.revokeObjectURL(preview.url);
      preview.element.remove();
      editor.getElementByKey(key)?.removeAttribute("data-mermaid-drawn");
      previews.delete(key);
    };

    const draw = async (key: NodeKey, preview: Preview) => {
      const code = editor.getElementByKey(key);
      const source = preview.source;
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: resolvedTheme === "dark" ? "dark" : "default",
          // Labels as SVG text, so the drawing survives being an image.
          htmlLabels: false,
          flowchart: { htmlLabels: false },
        });
        renderCount += 1;
        const { svg } = await mermaid.render(`mermaid-preview-${renderCount}`, source);
        if (previews.get(key) !== preview || preview.source !== source) return;
        if (preview.url) URL.revokeObjectURL(preview.url);
        preview.url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        const image = document.createElement("img");
        image.src = preview.url;
        image.alt = t("diagram");
        image.className = "mermaid-preview-image";
        preview.element.replaceChildren(image);
        preview.element.removeAttribute("data-error");
        code?.setAttribute("data-mermaid-drawn", "true");
      } catch (error) {
        if (previews.get(key) !== preview || preview.source !== source) return;
        const message = document.createElement("p");
        message.className = "mermaid-preview-error";
        message.textContent = t("diagramError", {
          message: error instanceof Error ? error.message.split("\n")[0] : "",
        });
        preview.element.replaceChildren(message);
        preview.element.setAttribute("data-error", "true");
        // A diagram that will not draw leaves its code showing to be fixed.
        code?.removeAttribute("data-mermaid-drawn");
      }
    };

    const sync = (key: NodeKey, source: string | null) => {
      if (source === null) {
        discard(key);
        return;
      }
      const code = editor.getElementByKey(key);
      if (!code) return;
      let preview = previews.get(key);
      if (!preview) {
        const element = document.createElement("div");
        element.className = "mermaid-preview";
        element.contentEditable = "false";
        setDOMUnmanaged(element, { captureSelection: true });
        preview = { element, source: "", timer: null, url: null };
        previews.set(key, preview);
      }
      // Right after its code block, wherever that block has moved to.
      if (code.nextSibling !== preview.element) {
        code.after(preview.element);
      }
      if (preview.source === source) return;
      preview.source = source;
      if (preview.timer) clearTimeout(preview.timer);
      const current = preview;
      current.timer = setTimeout(
        () => {
          current.timer = null;
          void draw(key, current);
        },
        // The first drawing is at once; later ones wait for typing to pause.
        current.url || current.element.hasChildNodes() ? REDRAW_DELAY_MS : 0
      );
    };

    const sourceOf = (key: NodeKey): string | null => {
      const node = $getNodeByKey(key);
      if (!$isCodeNode(node) || node.getLanguage() !== MERMAID_LANGUAGE) return null;
      const text = node.getTextContent().trim();
      return text === "" ? null : text;
    };

    const refreshAll = (target: LexicalEditor) => {
      target.getEditorState().read(() => {
        for (const key of [...previews.keys()]) {
          sync(key, sourceOf(key));
        }
      });
    };

    const unregister = mergeRegister(
      editor.registerMutationListener(
        CodeNode,
        (mutations) => {
          editor.getEditorState().read(() => {
            for (const [key, mutation] of mutations) {
              sync(key, mutation === "destroyed" ? null : sourceOf(key));
            }
          });
        },
        { skipInitialization: false }
      ),
      // A block moved by dragging keeps its node; this puts its picture back
      // underneath it.
      editor.registerUpdateListener(() => refreshAll(editor))
    );

    return () => {
      unregister();
      for (const key of [...previews.keys()]) {
        discard(key);
      }
    };
  }, [editor, resolvedTheme, t]);

  return null;
}

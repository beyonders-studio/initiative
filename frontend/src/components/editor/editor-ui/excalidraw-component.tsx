import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { ExcalidrawInitialDataState } from "@excalidraw/excalidraw/types";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useLexicalNodeSelection } from "@lexical/react/useLexicalNodeSelection";
import { mergeRegister } from "@lexical/utils";
import {
  $getNodeByKey,
  $getSelection,
  $isNodeSelection,
  CLICK_COMMAND,
  COMMAND_PRIORITY_LOW,
  KEY_BACKSPACE_COMMAND,
  KEY_DELETE_COMMAND,
  type NodeKey,
} from "lexical";
import { Loader2, PenTool } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { DrawingScene } from "@/components/editor/editor-ui/excalidraw-canvas";
import { $isExcalidrawNode } from "@/components/editor/nodes/excalidraw-node";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/ui/lib/utils";

// The canvas is the heaviest thing a document can load, so it arrives only
// when somebody opens a drawing — never for a page that merely shows one.
const DrawingCanvas = lazy(() => import("./excalidraw-canvas"));

type Scene = DrawingScene;

function parseScene(data: string): Scene {
  try {
    const parsed = JSON.parse(data) as Partial<Scene>;
    return {
      elements: Array.isArray(parsed.elements) ? parsed.elements : [],
      appState: parsed.appState && typeof parsed.appState === "object" ? parsed.appState : {},
      files: parsed.files && typeof parsed.files === "object" ? parsed.files : {},
    };
  } catch {
    return { elements: [], appState: {}, files: {} };
  }
}

const liveElements = (elements: readonly ExcalidrawElement[]) =>
  elements.filter((element) => !element.isDeleted);

interface ExcalidrawComponentProps {
  nodeKey: NodeKey;
  data: string;
  width: number;
}

/** A drawing on the page: its picture, and — for somebody who may edit — the
 * canvas to change it in. A new, empty drawing opens straight onto the
 * canvas; closing that without drawing anything takes the empty drawing
 * away again. */
export default function ExcalidrawComponent({ nodeKey, data, width }: ExcalidrawComponentProps) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const isEditable = useLexicalEditable();
  const { resolvedTheme } = useTheme();
  const [isSelected, setSelected, clearSelection] = useLexicalNodeSelection(nodeKey);
  const scene = useMemo(() => parseScene(data), [data]);
  const isEmpty = liveElements(scene.elements).length === 0;
  const [isOpen, setOpen] = useState(() => isEditable && isEmpty);
  const [picture, setPicture] = useState<string | null>(null);
  const previewRef = useRef<HTMLSpanElement | null>(null);

  // The picture, drawn from the scene each time it changes. Shown as an
  // image rather than as markup in the page, so nothing in a scene can do
  // more than be looked at.
  useEffect(() => {
    if (isEmpty) {
      setPicture(null);
      return;
    }
    let cancelled = false;
    let url: string | null = null;
    void import("@excalidraw/excalidraw").then(async ({ exportToSvg }) => {
      const drawn = await exportToSvg({
        elements: liveElements(scene.elements),
        appState: {
          ...scene.appState,
          exportBackground: false,
          exportWithDarkMode: resolvedTheme === "dark",
        },
        files: scene.files,
        exportPadding: 12,
      });
      if (cancelled) {
        return;
      }
      url = URL.createObjectURL(new Blob([drawn.outerHTML], { type: "image/svg+xml" }));
      setPicture(url);
    });
    return () => {
      cancelled = true;
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [scene, isEmpty, resolvedTheme]);

  const remove = useCallback(() => {
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isExcalidrawNode(node)) {
        node.remove();
      }
    });
  }, [editor, nodeKey]);

  const save = useCallback(
    (next: Scene) => {
      setOpen(false);
      if (liveElements(next.elements).length === 0) {
        remove();
        return;
      }
      editor.update(() => {
        const node = $getNodeByKey(nodeKey);
        if ($isExcalidrawNode(node)) {
          node.setData(JSON.stringify(next));
        }
      });
    },
    [editor, nodeKey, remove]
  );

  const cancel = useCallback(() => {
    setOpen(false);
    if (isEmpty) {
      remove();
    }
  }, [isEmpty, remove]);

  useEffect(() => {
    if (!isEditable) {
      return;
    }
    const $onDelete = (event: KeyboardEvent) => {
      const selection = $getSelection();
      if (isSelected && $isNodeSelection(selection)) {
        event.preventDefault();
        for (const node of selection.getNodes()) {
          if ($isExcalidrawNode(node)) {
            node.remove();
          }
        }
        return true;
      }
      return false;
    };
    return mergeRegister(
      editor.registerCommand<MouseEvent>(
        CLICK_COMMAND,
        (event) => {
          if (previewRef.current?.contains(event.target as Node)) {
            if (!event.shiftKey) {
              clearSelection();
            }
            setSelected(true);
            return true;
          }
          return false;
        },
        COMMAND_PRIORITY_LOW
      ),
      editor.registerCommand(KEY_DELETE_COMMAND, $onDelete, COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_BACKSPACE_COMMAND, $onDelete, COMMAND_PRIORITY_LOW)
    );
  }, [editor, isEditable, isSelected, setSelected, clearSelection]);

  const initialData: ExcalidrawInitialDataState = useMemo(
    () => ({
      elements: scene.elements,
      appState: { ...scene.appState, collaborators: new Map() },
      files: scene.files,
    }),
    [scene]
  );

  return (
    <>
      {!isEmpty && (
        <span
          ref={previewRef}
          className={cn(
            "group relative inline-block max-w-full rounded-md align-bottom",
            isSelected && isEditable && "ring-2 ring-primary"
          )}
          style={width > 0 ? { width } : undefined}
          onDoubleClick={() => isEditable && setOpen(true)}
        >
          {picture ? (
            <img src={picture} alt={t("drawing")} className="block max-w-full" draggable={false} />
          ) : (
            <span className="flex h-24 w-48 items-center justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </span>
          )}
          {isEditable && (
            // Shown on hover, and once the drawing is tapped: a touch screen
            // has no hover and no double tap it will pass on.
            <button
              type="button"
              className={cn(
                "absolute top-2 right-2 items-center rounded-md border bg-background px-2 py-1 text-xs shadow-sm",
                isSelected ? "inline-flex" : "hidden group-hover:inline-flex"
              )}
              onClick={() => setOpen(true)}
            >
              <PenTool className="mr-1 h-3.5 w-3.5" />
              {t("editDrawing")}
            </button>
          )}
        </span>
      )}
      {isOpen &&
        createPortal(
          <div className="fixed inset-0 z-50 bg-background/80 p-2 sm:p-6">
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              }
            >
              <DrawingCanvas
                initialData={initialData}
                theme={resolvedTheme}
                onSave={save}
                onCancel={cancel}
              />
            </Suspense>
          </div>,
          document.body
        )}
    </>
  );
}

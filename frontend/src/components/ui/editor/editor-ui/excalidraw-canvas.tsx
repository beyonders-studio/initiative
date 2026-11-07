import { Excalidraw, serializeAsJSON } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type {
  AppState,
  BinaryFiles,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from "@excalidraw/excalidraw/types";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { renderEmbeddable, validateEmbeddable } from "@/lib/whiteboardEmbeds";

export interface DrawingScene {
  elements: readonly ExcalidrawElement[];
  appState: Partial<AppState>;
  files: BinaryFiles;
}

interface DrawingCanvasProps {
  initialData: ExcalidrawInitialDataState;
  theme: "light" | "dark";
  onSave: (scene: DrawingScene) => void;
  onCancel: () => void;
}

/** The whiteboard editor, on one drawing. Saving hands back the scene in the
 * shape a whiteboard file stores; cancelling hands back nothing. */
export default function DrawingCanvas({
  initialData,
  theme,
  onSave,
  onCancel,
}: DrawingCanvasProps) {
  const { t } = useTranslation("editor");
  const api = useRef<ExcalidrawImperativeAPI | null>(null);

  const handleSave = () => {
    const current = api.current;
    if (!current) {
      onCancel();
      return;
    }
    const elements = current.getSceneElements();
    const allFiles = current.getFiles();
    // The same trimmed form a whiteboard file saves: what is on the
    // canvas, the view settings worth keeping, and only the pictures still
    // in use.
    const serialized = JSON.parse(
      serializeAsJSON(elements, current.getAppState(), allFiles, "database")
    ) as { elements: ExcalidrawElement[]; appState: Partial<AppState> };
    const used = new Set(
      elements.flatMap((element) =>
        "fileId" in element && element.fileId ? [String(element.fileId)] : []
      )
    );
    const files: BinaryFiles = {};
    for (const [id, file] of Object.entries(allFiles)) {
      if (used.has(id)) {
        files[id] = file;
      }
    }
    onSave({ elements: serialized.elements, appState: serialized.appState, files });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border bg-background shadow-lg">
      <div className="min-h-0 flex-1">
        <Excalidraw
          excalidrawAPI={(instance) => {
            api.current = instance;
          }}
          initialData={initialData}
          theme={theme}
          validateEmbeddable={validateEmbeddable}
          renderEmbeddable={renderEmbeddable}
        />
      </div>
      <div className="flex justify-end gap-2 border-t p-2">
        <Button variant="outline" onClick={onCancel}>
          {t("cancelDrawing")}
        </Button>
        <Button onClick={handleSave}>{t("saveDrawing")}</Button>
      </div>
    </div>
  );
}

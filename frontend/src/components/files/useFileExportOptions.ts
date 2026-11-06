import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { FileType } from "@/api/generated/initiativeAPI.schemas";
import { fileTypeFormats } from "@/components/exports/formats";
import type { WhiteboardScene } from "@/components/files/WhiteboardFileEditor";
import type { ToolExportOptions } from "@/components/tools/settings/ToolSettingsContext";
import { downloadBlob } from "@/lib/csv";
import { exportFilenameStem } from "@/lib/exportDownload";
import { toast } from "@/lib/mascotToast";

/**
 * What a file's export card offers: the engine formats its type has, and
 * — for a whiteboard — PNG and SVG, which only Excalidraw's own renderer draws
 * faithfully, so they are made in the browser from the scene while the engine
 * handles the importable JSON.
 */
export function useFileExportOptions(
  fileType: FileType,
  title: string,
  whiteboardScene?: WhiteboardScene
): ToolExportOptions {
  const { t } = useTranslation("exports");
  const stem = exportFilenameStem(title, "file");
  // Engine entries are debounced by ExportButton's busy state; the
  // client-side renders need their own in-flight guard.
  const sceneExporting = useRef(false);

  const exportScene = async (kind: "png" | "svg") => {
    if (!whiteboardScene || sceneExporting.current) {
      return;
    }
    sceneExporting.current = true;
    try {
      // Lazy: the excalidraw bundle is heavy.
      const { exportToBlob, exportToSvg } = await import("@excalidraw/excalidraw");
      if (kind === "png") {
        const blob = await exportToBlob({
          elements: whiteboardScene.elements,
          appState: whiteboardScene.appState,
          files: whiteboardScene.files,
          mimeType: "image/png",
        });
        downloadBlob(blob, `${stem}.png`);
      } else {
        const svg = await exportToSvg({
          elements: whiteboardScene.elements,
          appState: whiteboardScene.appState,
          files: whiteboardScene.files,
        });
        const blob = new Blob([svg.outerHTML], { type: "image/svg+xml" });
        downloadBlob(blob, `${stem}.svg`);
      }
      toast.success(t("export.success"));
    } catch {
      toast.error(t("export.error"));
    } finally {
      sceneExporting.current = false;
    }
  };

  return {
    formats: fileTypeFormats(fileType),
    extraActions:
      fileType === FileType.excalidraw && whiteboardScene
        ? [
            { labelKey: "export.formatPng", onSelect: () => void exportScene("png") },
            { labelKey: "export.formatSvg", onSelect: () => void exportScene("svg") },
          ]
        : undefined,
  };
}

import { type DragEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { matchesAccept } from "@/lib/fileUtils";
import { toast } from "@/lib/mascotToast";

interface FileDropOptions {
  /**
   * An `accept` list of extensions. A file picker filters by it itself; a file
   * dragged from the desktop skips the picker, so a drop is checked here, and a
   * drop with nothing acceptable in it says so rather than doing nothing.
   */
  accept?: string;
}

/**
 * Make an element a place to drop files from outside the page.
 *
 * Spread `handlers` on the element and draw an overlay while `dragging`. A
 * counter rather than a boolean tracks the drag, because `dragenter` and
 * `dragleave` fire for every child the cursor crosses and a boolean would
 * flicker the overlay off over each one.
 *
 * A drag that began on the page — a picture, a link, a selection — is not files
 * arriving, whatever the browser puts in its types list, so only a drag that
 * started elsewhere is taken.
 */
export const useFileDrop = (
  enabled: boolean,
  onFiles: (files: File[]) => void,
  { accept }: FileDropOptions = {}
) => {
  const { t } = useTranslation("common");
  const depth = useRef(0);
  const internalDrag = useRef(false);
  const [dragging, setDragging] = useState(false);

  const hasFiles = (event: DragEvent) =>
    enabled && !internalDrag.current && Array.from(event.dataTransfer.types).includes("Files");

  const handlers = {
    onDragStart: () => {
      internalDrag.current = true;
    },
    onDragEnd: () => {
      internalDrag.current = false;
    },
    onDragEnter: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      // React carries events up through portals, so a drop target inside a
      // dialog would otherwise hand the same files to the page behind it.
      event.stopPropagation();
      depth.current = 0;
      setDragging(false);
      const dropped = Array.from(event.dataTransfer.files);
      const files = accept ? dropped.filter((file) => matchesAccept(file.name, accept)) : dropped;
      if (files.length > 0) onFiles(files);
      else if (dropped.length > 0) toast.error(t("fileDrop.unsupported"));
    },
  };

  return { dragging: enabled && dragging, handlers };
};

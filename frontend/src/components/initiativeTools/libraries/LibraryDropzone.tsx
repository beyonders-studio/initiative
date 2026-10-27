import { ImagePlus } from "lucide-react";
import { forwardRef, type ReactNode, useImperativeHandle, useRef } from "react";
import { useTranslation } from "react-i18next";

import { DropOverlay } from "@/components/ui/file-drop";
import { useFileDrop } from "@/hooks/useFileDrop";
import { ACCEPT_ATTRIBUTE } from "@/lib/libraries";
import { cn } from "@/lib/utils";

export interface LibraryDropzoneHandle {
  /** Open the file dialog — for a button somewhere else on the page. */
  open: () => void;
}

interface LibraryDropzoneProps {
  /** Whether dropping does anything. A reader without write access sees the
   *  wall and no overlay. */
  enabled: boolean;
  onFiles: (files: File[]) => void;
  className?: string;
  children: ReactNode;
}

/**
 * The wall as a place to drop pictures.
 *
 * Wraps the whole library rather than offering a box at the top: forty files
 * dragged from a folder land wherever the cursor is, and the cursor is over
 * the pictures.
 *
 * The same component owns the file input, so "Add pictures" and a drop go
 * through one `onFiles`.
 */
export const LibraryDropzone = forwardRef<LibraryDropzoneHandle, LibraryDropzoneProps>(
  ({ enabled, onFiles, className, children }, ref) => {
    const { t } = useTranslation("libraries");
    const inputRef = useRef<HTMLInputElement | null>(null);
    const drop = useFileDrop(enabled, onFiles);

    useImperativeHandle(ref, () => ({ open: () => inputRef.current?.click() }), []);

    return (
      <div className={cn("relative", className)} {...drop.handlers}>
        {children}
        {enabled && (
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            multiple
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              // The same file twice in a row is a new choice, not a repeat.
              event.target.value = "";
              if (files.length > 0) onFiles(files);
            }}
          />
        )}
        {drop.dragging && <DropOverlay icon={ImagePlus} label={t("dropzone.prompt")} tall />}
      </div>
    );
  }
);
LibraryDropzone.displayName = "LibraryDropzone";

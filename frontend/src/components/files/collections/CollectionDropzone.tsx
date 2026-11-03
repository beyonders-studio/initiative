import { Upload } from "lucide-react";
import { forwardRef, type ReactNode, useImperativeHandle, useRef } from "react";
import { useTranslation } from "react-i18next";

import { DropOverlay } from "@/components/ui/file-drop";
import { useFileDrop } from "@/hooks/useFileDrop";
import { cn } from "@/lib/utils";

export interface CollectionDropzoneHandle {
  /** Open the file dialog — for a button somewhere else on the page. */
  open: () => void;
}

interface CollectionDropzoneProps {
  /** Whether dropping does anything. A reader who may not change the
   *  collection sees the wall and no overlay. */
  enabled: boolean;
  onFiles: (files: File[]) => void;
  className?: string;
  children: ReactNode;
}

/**
 * The wall as a place to drop files.
 *
 * Wraps the whole collection rather than offering a box at the top: forty
 * files dragged from a folder land wherever the cursor is, and the cursor is
 * over the wall.
 *
 * The same component owns the file input, so "Upload files" and a drop go
 * through one `onFiles`.
 */
export const CollectionDropzone = forwardRef<CollectionDropzoneHandle, CollectionDropzoneProps>(
  ({ enabled, onFiles, className, children }, ref) => {
    const { t } = useTranslation("files");
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
        {drop.dragging && <DropOverlay icon={Upload} label={t("collections.dropPrompt")} tall />}
      </div>
    );
  }
);
CollectionDropzone.displayName = "CollectionDropzone";

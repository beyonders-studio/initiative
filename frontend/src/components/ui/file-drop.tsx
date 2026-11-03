import { type LucideIcon, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ImagePicker } from "@/components/ui/image-picker";
import { useFileDrop } from "@/hooks/useFileDrop";
import { cn } from "@/lib/utils";

interface DropOverlayProps {
  /** What dropping here will do, said while the files are over it. */
  label: string;
  icon?: LucideIcon;
  /**
   * The region can run past the bottom of the screen — a page, a long wall of
   * pictures. The label then rides along a third of the way down the view
   * instead of sitting in the middle of the region, where it may be out of
   * sight.
   */
  tall?: boolean;
  className?: string;
}

/**
 * What a whole region shows while files are dragged over it.
 *
 * Laid over the region rather than beside it — the parent needs `relative` —
 * and deaf to the pointer, so the drag keeps landing on the region itself.
 */
export const DropOverlay = ({
  label,
  icon: Icon = Upload,
  tall = false,
  className,
}: DropOverlayProps) => (
  <div
    className={cn(
      "pointer-events-none absolute inset-0 z-20 flex justify-center rounded-xl border-2 border-primary border-dashed bg-background/80 backdrop-blur-sm",
      tall ? "items-start" : "items-center",
      className
    )}
  >
    <div
      className={cn("flex flex-col items-center gap-2 text-primary", tall && "sticky top-1/3 py-8")}
    >
      <Icon className="size-10" aria-hidden />
      <p className="font-medium">{label}</p>
    </div>
  </div>
);

interface FileDropAreaProps {
  /** An `accept` list of extensions, for the picker and for a drop alike;
   *  any file without one. */
  accept?: string;
  onFile: (file: File) => void;
  /** The line above the button, saying what a file dropped here becomes. */
  prompt: string;
  disabled?: boolean;
  className?: string;
}

/**
 * A box to drop one file in, with a button for where there is nothing to drag.
 *
 * On a phone the button is the whole of it, so the button is always there; the
 * drop is what a desktop adds. The button goes through the app's picker, which
 * offers the camera first on the native app.
 */
export const FileDropArea = ({
  accept,
  onFile,
  prompt,
  disabled = false,
  className,
}: FileDropAreaProps) => {
  const { t } = useTranslation("common");
  const drop = useFileDrop(
    !disabled,
    (files) => {
      const [first] = files;
      if (first) onFile(first);
    },
    { accept }
  );

  return (
    <div
      {...drop.handlers}
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border border-dashed p-4 text-center transition-colors",
        drop.dragging && "border-primary bg-primary/5",
        className
      )}
    >
      <p className="text-muted-foreground text-sm">
        {drop.dragging ? t("fileDrop.release") : prompt}
      </p>
      <ImagePicker
        variant="button"
        buttonSize="sm"
        accept={accept ?? ""}
        onSelect={onFile}
        disabled={disabled}
      >
        <Upload className="h-4 w-4" />
        {t("imagePicker.chooseFile")}
      </ImagePicker>
    </div>
  );
};

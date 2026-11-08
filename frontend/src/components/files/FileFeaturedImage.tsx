import { Camera, FolderOpen, ImagePlus, Images, Upload, X } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ImageChooserDialog } from "@/components/files/ImageChooser";
import { canCapturePhoto } from "@/lib/nativeCamera";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { ImagePicker, usePhotoCapture } from "@/ui/image-picker";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

interface FileFeaturedImageProps {
  url: string | null;
  canEdit: boolean;
  uploading: boolean;
  onUpload: (file: File) => void;
  /** The initiative whose pictures in Files the chooser opens on. */
  initiativeId: number;
  /** Called with the address of a picture picked from Files. */
  onChoose: (url: string) => void;
  onRemove: () => void;
}

/** A control named by its tooltip. The trigger wraps it, because the picker
 *  renders its own button. */
const Tip = ({ label, children }: { label: string; children: ReactNode }) => (
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="inline-flex">{children}</span>
    </TooltipTrigger>
    <TooltipContent>{label}</TooltipContent>
  </Tooltip>
);

/**
 * The picture a file leads with, and the one its card shows.
 *
 * Set, it runs the width of the file at its own shape, never cropped, and
 * no taller than most of the screen, with its controls over its corner. Unset,
 * a writer gets one quiet "Add featured image" button, there before a word is
 * written, whose menu uploads one or picks one already in Files (as the
 * version it is now); a reader sees nothing. A picture written into the body
 * can be made the featured one from the picture itself, so this is one of two
 * ways in.
 */
export const FileFeaturedImage = ({
  url,
  canEdit,
  uploading,
  onUpload,
  initiativeId,
  onChoose,
  onRemove,
}: FileFeaturedImageProps) => {
  const { t } = useTranslation(["files", "ui"]);
  const [choosing, setChoosing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const { capturing, capture } = usePhotoCapture(onUpload);

  if (!url && !canEdit) return null;

  const chooser = (
    <ImageChooserDialog
      open={choosing}
      onOpenChange={setChoosing}
      initiativeId={initiativeId}
      onPick={(image) => onChoose(image.src)}
    />
  );

  if (!url) {
    const busy = uploading || capturing;
    return (
      <div>
        <input
          ref={input}
          type="file"
          accept="image/*"
          className="hidden"
          tabIndex={-1}
          aria-hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            // Cleared so choosing the same picture twice in a row still fires.
            event.target.value = "";
            if (file) onUpload(file);
          }}
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              pending={busy}
            >
              <ImagePlus aria-hidden />
              {uploading ? t("featuredImage.uploading") : t("featuredImage.add")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {/* The app offers the camera first, as every picture control there does. */}
            {canCapturePhoto() ? (
              <>
                <DropdownMenuItem onSelect={() => void capture("camera")}>
                  <Camera aria-hidden />
                  {t("ui:imagePicker.takePhoto")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void capture("library")}>
                  <Images aria-hidden />
                  {t("ui:imagePicker.chooseFromLibrary")}
                </DropdownMenuItem>
              </>
            ) : (
              <DropdownMenuItem onSelect={() => input.current?.click()}>
                <Upload aria-hidden />
                {t("featuredImage.upload")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => setChoosing(true)}>
              <FolderOpen aria-hidden />
              {t("featuredImage.fromFiles")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {chooser}
      </div>
    );
  }

  const replaceLabel = uploading ? t("featuredImage.uploading") : t("featuredImage.replace");

  return (
    <figure className="group relative overflow-hidden rounded-xl border bg-muted">
      <img
        src={resolveUploadUrl(url) ?? undefined}
        alt={t("featuredImage.label")}
        referrerPolicy="no-referrer"
        className="max-h-[60vh] w-full object-contain"
      />
      {canEdit ? (
        <div className="absolute top-2 right-2 flex gap-1.5 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
          {/* Its own provider: there is none at the app root. */}
          <TooltipProvider delayDuration={300}>
            <Tip label={replaceLabel}>
              <ImagePicker
                variant="button"
                buttonVariant="secondary"
                buttonSize="icon-sm"
                accept="image/*"
                pending={uploading}
                onSelect={onUpload}
              >
                <ImagePlus aria-hidden />
                <span className="sr-only">{replaceLabel}</span>
              </ImagePicker>
            </Tip>
            <Tip label={t("featuredImage.replaceFromFiles")}>
              <Button
                type="button"
                variant="secondary"
                size="icon-sm"
                disabled={uploading}
                onClick={() => setChoosing(true)}
                aria-label={t("featuredImage.replaceFromFiles")}
              >
                <FolderOpen aria-hidden />
              </Button>
            </Tip>
            <Tip label={t("featuredImage.remove")}>
              <Button
                type="button"
                variant="secondary"
                size="icon-sm"
                onClick={onRemove}
                disabled={uploading}
                aria-label={t("featuredImage.remove")}
              >
                <X aria-hidden />
              </Button>
            </Tip>
          </TooltipProvider>
          {chooser}
        </div>
      ) : null}
    </figure>
  );
};

import { FolderOpen, ImageIcon, ImagePlus, Loader2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ImageChooserDialog } from "@/components/files/ImageChooser";
import { Button } from "@/components/ui/button";
import { ImagePicker } from "@/components/ui/image-picker";
import { resolveUploadUrl } from "@/lib/uploadUrl";

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

/**
 * The picture a file leads with, and the one its card shows.
 *
 * Set, it runs the width of the file at its own shape, never cropped, and
 * no taller than most of the screen. Unset, a writer gets one small row
 * to add it from, there before a word is written; a reader sees nothing. A
 * picture written into the body can be made the featured one from the picture
 * itself, so this row is one of two ways in. A picture already in Files can
 * be picked too, as the version it is now.
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
  const { t } = useTranslation("files");
  const [choosing, setChoosing] = useState(false);

  const upload = (label: string, variant: "secondary" | "ghost") => (
    <ImagePicker
      variant="button"
      buttonVariant={variant}
      buttonSize="sm"
      accept="image/*"
      disabled={uploading}
      onSelect={onUpload}
    >
      {uploading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        <ImagePlus className="h-4 w-4" aria-hidden />
      )}
      {uploading ? t("featuredImage.uploading") : label}
    </ImagePicker>
  );

  const choose = (variant: "secondary" | "ghost") => (
    <>
      <Button
        type="button"
        variant={variant}
        size="sm"
        disabled={uploading}
        onClick={() => setChoosing(true)}
      >
        <FolderOpen className="h-4 w-4" aria-hidden />
        {t("featuredImage.fromFiles")}
      </Button>
      <ImageChooserDialog
        open={choosing}
        onOpenChange={setChoosing}
        initiativeId={initiativeId}
        onPick={(image) => onChoose(image.src)}
      />
    </>
  );

  if (url) {
    return (
      <figure className="group relative overflow-hidden rounded-xl border bg-muted">
        <img
          src={resolveUploadUrl(url) ?? undefined}
          alt={t("featuredImage.label")}
          referrerPolicy="no-referrer"
          className="max-h-[60vh] w-full object-contain"
        />
        {canEdit ? (
          <div className="absolute top-2 right-2 flex gap-2 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
            {upload(t("featuredImage.replace"), "secondary")}
            {choose("secondary")}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onRemove}
              disabled={uploading}
            >
              <X className="h-4 w-4" aria-hidden />
              {t("featuredImage.remove")}
            </Button>
          </div>
        ) : null}
      </figure>
    );
  }

  if (!canEdit) return null;

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-12 shrink-0 items-center justify-center rounded-md border border-dashed text-muted-foreground">
        <ImageIcon className="h-4 w-4" aria-hidden />
      </div>
      <span className="text-muted-foreground text-sm">{t("featuredImage.label")}</span>
      {upload(t("featuredImage.upload"), "ghost")}
      {choose("ghost")}
    </div>
  );
};

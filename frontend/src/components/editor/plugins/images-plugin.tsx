import type { LexicalEditor } from "lexical";
import { type JSX, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useEditorInitiative } from "@/components/editor/context/editor-initiative-context";
import { ImageChooser } from "@/components/tools/files/ImageChooser";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { uploadAttachment } from "@/lib/attachmentUtils";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { DialogFooter } from "@/ui/dialog";
import { useFeaturedImage } from "@/ui/editor/context/featured-image-context";
import {
  INSERT_IMAGE_COMMAND,
  type InsertImagePayload,
} from "@/ui/editor/extensions/images-extension";
import { Field } from "@/ui/field";
import { ImagePicker } from "@/ui/image-picker";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/ui/tabs";

export function InsertImageUriDialogBody({
  onClick,
}: {
  onClick: (payload: InsertImagePayload) => void;
}) {
  const { t } = useTranslation(["editor", "common"]);
  const [src, setSrc] = useState("");
  const [altText, setAltText] = useState("");

  const isDisabled = src === "";

  return (
    <div className="grid gap-4 py-4">
      <Field label={t("imageDialog.imageUrl")}>
        <Input
          placeholder={t("imageDialog.imageUrlPlaceholder")}
          onChange={(e) => setSrc(e.target.value)}
          value={src}
          data-test-id="image-modal-url-input"
        />
      </Field>
      <Field label={t("imageDialog.altText")}>
        <Input
          placeholder={t("imageDialog.altTextPlaceholder")}
          onChange={(e) => setAltText(e.target.value)}
          value={altText}
          data-test-id="image-modal-alt-text-input"
        />
      </Field>
      <DialogFooter>
        <Button
          type="submit"
          disabled={isDisabled}
          onClick={() => onClick({ altText, src })}
          data-test-id="image-modal-confirm-btn"
        >
          {t("common:confirm")}
        </Button>
      </DialogFooter>
    </div>
  );
}

/** What the upload and Files tabs share once a picture is in hand: its alt
 *  text, whether it becomes the featured image, and the confirm. */
function InsertImageDetails({
  src,
  altText,
  onAltTextChange,
  busy = false,
  onClick,
  confirmTestId,
}: {
  src: string;
  altText: string;
  onAltTextChange: (altText: string) => void;
  busy?: boolean;
  onClick: (payload: InsertImagePayload) => void;
  confirmTestId: string;
}) {
  const { t } = useTranslation(["editor", "common"]);
  const featured = useFeaturedImage();
  const featuredId = useId();
  const [makeFeatured, setMakeFeatured] = useState(false);

  return (
    <>
      <Field label={t("imageDialog.altText")}>
        <Input
          placeholder={t("imageDialog.altTextPlaceholder")}
          onChange={(e) => onAltTextChange(e.target.value)}
          value={altText}
          data-test-id="image-modal-alt-text-input"
        />
      </Field>
      {featured ? (
        <div className="flex items-center gap-2">
          <Checkbox
            id={featuredId}
            checked={makeFeatured}
            onCheckedChange={(checked) => setMakeFeatured(checked === true)}
          />
          <Label htmlFor={featuredId}>{t("featuredImage.makeFeatured")}</Label>
        </div>
      ) : null}
      <Button
        type="submit"
        disabled={src === "" || busy}
        onClick={() => {
          if (makeFeatured) featured?.set(src);
          onClick({ altText, src });
        }}
        data-test-id={confirmTestId}
      >
        {busy ? t("imageDialog.uploading") : t("common:confirm")}
      </Button>
    </>
  );
}

export function InsertImageUploadedDialogBody({
  onClick,
}: {
  onClick: (payload: InsertImagePayload) => void;
}) {
  const { t } = useTranslation(["editor", "common"]);
  const communityId = useActiveCommunityId();
  const [src, setSrc] = useState("");
  const [altText, setAltText] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [fileName, setFileName] = useState("");

  const handleFileChange = async (file: File) => {
    setFileName(file.name);
    setAltText(file.name);
    setIsUploading(true);

    try {
      const response = await uploadAttachment(communityId, file);
      setSrc(response.url);
    } catch (error) {
      console.error("Failed to upload image:", error);
      setSrc("");
      setFileName("");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="grid gap-4 py-4">
      <div className="grid gap-2">
        <Label htmlFor="image-upload">{t("imageDialog.upload")}</Label>
        <ImagePicker
          id="image-upload"
          onSelect={(file) => handleFileChange(file)}
          accept="image/*"
          disabled={isUploading}
          data-test-id="image-modal-file-upload"
        />
        {isUploading && (
          <p className="text-muted-foreground text-sm">
            {t("imageDialog.uploadingFile", { name: fileName })}
          </p>
        )}
      </div>
      <InsertImageDetails
        src={src}
        altText={altText}
        onAltTextChange={setAltText}
        busy={isUploading}
        onClick={onClick}
        confirmTestId="image-modal-file-upload-btn"
      />
    </div>
  );
}

/** A picture already in Files, put into the page as the version picked. */
export function InsertImageFromFilesDialogBody({
  initiativeId,
  onClick,
}: {
  initiativeId: number;
  onClick: (payload: InsertImagePayload) => void;
}) {
  const [src, setSrc] = useState("");
  const [altText, setAltText] = useState("");

  return (
    <div className="grid gap-4 py-4">
      <ImageChooser
        initiativeId={initiativeId}
        picked={src}
        onPick={(image) => {
          setSrc(image.src);
          setAltText(image.name);
        }}
      />
      <InsertImageDetails
        src={src}
        altText={altText}
        onAltTextChange={setAltText}
        onClick={onClick}
        confirmTestId="image-modal-files-btn"
      />
    </div>
  );
}

export function InsertImageDialog({
  activeEditor,
  onClose,
}: {
  activeEditor: LexicalEditor;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation("editor");
  // Pictures in Files are an initiative's, so a page outside one has none to
  // offer.
  const initiativeId = useEditorInitiative();
  const hasModifier = useRef(false);

  useEffect(() => {
    hasModifier.current = false;
    const handler = (e: KeyboardEvent) => {
      hasModifier.current = e.altKey;
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
    };
  }, [activeEditor]);

  const onClick = (payload: InsertImagePayload) => {
    activeEditor.dispatchCommand(INSERT_IMAGE_COMMAND, payload);
    onClose();
  };

  return (
    <Tabs defaultValue="url">
      <TabsBar>
        <TabsTrigger value="url">{t("imageDialog.urlTab")}</TabsTrigger>
        <TabsTrigger value="file">{t("imageDialog.fileTab")}</TabsTrigger>
        {initiativeId !== null ? (
          <TabsTrigger value="files">{t("imageDialog.filesTab")}</TabsTrigger>
        ) : null}
      </TabsBar>
      <TabsContent value="url">
        <InsertImageUriDialogBody onClick={onClick} />
      </TabsContent>
      <TabsContent value="file">
        <InsertImageUploadedDialogBody onClick={onClick} />
      </TabsContent>
      {initiativeId !== null ? (
        <TabsContent value="files">
          <InsertImageFromFilesDialogBody initiativeId={initiativeId} onClick={onClick} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}

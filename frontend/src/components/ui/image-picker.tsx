import { Camera, ImagePlus, Images, Paperclip } from "lucide-react";
import { type ChangeEvent, type ReactNode, useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { toast } from "@/lib/mascotToast";
import {
  canCapturePhoto,
  capturePhoto,
  PhotoCaptureError,
  type PhotoSource,
} from "@/lib/nativeCamera";

/**
 * One way to hand the app a picture, wherever the app runs.
 *
 * In a browser this is the file field it has always been. On the native app it
 * becomes a menu offering the camera first, because the phone in someone's hand
 * is usually where the picture they want does not exist yet — the alternative is
 * take a photo, save it, come back, and find it in a picker.
 */

const IMAGE_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".svg",
  ".avif",
  ".heic",
  ".heif",
  ".bmp",
]);

/** Whether this accept list would also take something that is not an image.
 *  An empty one takes anything. */
export const acceptsNonImages = (accept: string): boolean =>
  !accept.trim() ||
  accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean)
    .some(
      (token) =>
        !token.startsWith("image/") && !["*", "*/*"].includes(token) && !IMAGE_EXTENSIONS.has(token)
    );

/**
 * Taking a picture with the camera, or choosing one from the photo library, on
 * the native app — what every picture control there offers before a file
 * dialog. Only meaningful where `canCapturePhoto()` says so.
 */
export function usePhotoCapture(onSelect: (file: File) => void | Promise<void>) {
  const { t } = useTranslation("common");
  const [capturing, setCapturing] = useState(false);
  // Read at the moment a picture arrives, so a caller passing a fresh function
  // each render does not make `capture` a new function each render too.
  const latestOnSelect = useRef(onSelect);
  latestOnSelect.current = onSelect;

  const capture = useCallback(
    async (source: PhotoSource) => {
      setCapturing(true);
      try {
        const file = await capturePhoto(source);
        // No file means the person backed out, which needs no announcement.
        if (file) await latestOnSelect.current(file);
      } catch (error) {
        console.error(error);
        const reason = error instanceof PhotoCaptureError ? error.reason : "failed";
        toast.error(t(`imagePicker.${reason}`));
      } finally {
        setCapturing(false);
      }
    },
    [t]
  );

  return { capturing, capture };
}

interface ImagePickerProps {
  /** Called with the chosen picture — from the camera, the library, or a file. */
  onSelect: (file: File) => void | Promise<void>;
  /** Same meaning as the attribute it replaces. */
  accept?: string;
  disabled?: boolean;
  /** Lands on whichever control is rendered, so a `<Label htmlFor>` still points at it. */
  id?: string;
  className?: string;
  /**
   * Off-native shape: the file field itself, or a button that opens the file
   * dialog. On native both become the same menu button.
   */
  variant?: "input" | "button";
  /** Button content. Ignored by `variant="input"` off-native, where there is no button. */
  children?: ReactNode;
  buttonVariant?: React.ComponentProps<typeof Button>["variant"];
  buttonSize?: React.ComponentProps<typeof Button>["size"];
  "data-test-id"?: string;
}

export const ImagePicker = ({
  onSelect,
  accept = "image/*",
  disabled = false,
  id,
  className,
  variant = "input",
  children,
  buttonVariant = "outline",
  buttonSize,
  "data-test-id": dataTestId,
}: ImagePickerProps) => {
  const { t } = useTranslation("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const { capturing, capture } = usePhotoCapture(onSelect);

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Clear it so picking the same file twice in a row still fires a change.
    event.target.value = "";
    if (file) void onSelect(file);
  };

  const fileInput = (
    <Input
      ref={inputRef}
      id={variant === "input" ? id : undefined}
      type="file"
      accept={accept}
      disabled={disabled}
      onChange={handleInput}
      className={variant === "button" || canCapturePhoto() ? "hidden" : className}
      data-test-id={dataTestId}
      // A control the person never sees should not be a tab stop of its own.
      tabIndex={variant === "button" || canCapturePhoto() ? -1 : undefined}
      aria-hidden={variant === "button" || canCapturePhoto() ? true : undefined}
    />
  );

  const label = children ?? (
    <>
      <ImagePlus className="h-4 w-4" />
      {t("imagePicker.chooseImage")}
    </>
  );

  if (!canCapturePhoto()) {
    if (variant === "input") return fileInput;
    return (
      <>
        {fileInput}
        <Button
          type="button"
          id={id}
          variant={buttonVariant}
          size={buttonSize}
          disabled={disabled}
          className={className}
          onClick={() => inputRef.current?.click()}
        >
          {label}
        </Button>
      </>
    );
  }

  return (
    <>
      {fileInput}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            id={id}
            variant={buttonVariant}
            size={buttonSize}
            disabled={disabled || capturing}
            className={className}
            data-test-id={dataTestId ? `${dataTestId}-menu` : undefined}
          >
            {label}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onSelect={() => void capture("camera")}>
            <Camera className="h-4 w-4" />
            {t("imagePicker.takePhoto")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void capture("library")}>
            <Images className="h-4 w-4" />
            {t("imagePicker.chooseFromLibrary")}
          </DropdownMenuItem>
          {acceptsNonImages(accept) ? (
            <DropdownMenuItem onSelect={() => inputRef.current?.click()}>
              <Paperclip className="h-4 w-4" />
              {t("imagePicker.chooseFile")}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
};

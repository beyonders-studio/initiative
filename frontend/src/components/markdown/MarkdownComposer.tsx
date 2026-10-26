import { Camera, ImagePlus, Images } from "lucide-react";
import {
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Markdown } from "@/components/Markdown";
import { usePhotoCapture } from "@/components/ui/image-picker";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  continueList,
  imageMarkdown,
  imagesIn,
  type MarkdownSelection,
  type MarkdownTransform,
} from "@/lib/markdownEditing";
import { toast } from "@/lib/mascotToast";
import { canCapturePhoto } from "@/lib/nativeCamera";
import { cn } from "@/lib/utils";

import { MARKDOWN_SHORTCUTS, MarkdownToolbar, type ToolbarItem } from "./MarkdownToolbar";

type ComposerMode = "write" | "preview";

interface MarkdownComposerProps {
  value: string;
  onChange: (value: string) => void;
  /** What the preview tab shows. Defaults to the same markdown renderer the
   *  rest of the product reads prose with. `onChange` is there for a
   *  checklist box ticked in the preview. */
  renderPreview?: (value: string, onChange?: (value: string) => void) => ReactNode;
  id?: string;
  placeholder?: string;
  rows?: number;
  /** The most characters the text may hold, as the server allows. */
  maxLength?: number;
  disabled?: boolean;
  autoFocus?: boolean;
  /** The caller's own handle on the field — for caret measurement, focus, and
   *  anything else that needs the element itself. */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  /** Absolutely positioned against the field, so it can anchor to the caret.
   *  The mention popover lives here. */
  overlay?: ReactNode;
  /** Extra controls beside the tabs — an AI action, say. */
  actions?: ReactNode;
  /** A surface's own toolbar actions, which share the row's overflow menu.
   *  A comment's mention triggers are these. */
  tools?: ToolbarItem[];
  /** Stores a pasted, dropped or chosen picture and answers with its address.
   *  Without it, the field takes text only. */
  onUploadImage?: (file: File) => Promise<string>;
  /** Shrinks the chrome for a reply box or an inline edit. */
  compact?: boolean;
  /** Which tab the field opens on. A surface whose text is usually read
   *  before it is changed — a task's description — opens on `"preview"`. */
  defaultMode?: ComposerMode;
  className?: string;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSelect?: () => void;
  onBlur?: () => void;
}

/**
 * A markdown field with the two things writing markdown needs: buttons for the
 * syntax nobody remembers, and a way to see what it will look like before
 * committing to it.
 *
 * The field itself stays plain markdown source — switching to Preview hides it
 * rather than replacing it, so the caret, the scroll position, and anything
 * anchored to them survive the round trip.
 */
export const MarkdownComposer = ({
  value,
  onChange,
  renderPreview,
  id,
  placeholder,
  rows,
  maxLength,
  disabled = false,
  autoFocus = false,
  textareaRef,
  overlay,
  actions,
  tools,
  onUploadImage,
  compact = false,
  defaultMode = "write",
  className,
  onKeyDown,
  onSelect,
  onBlur,
}: MarkdownComposerProps) => {
  const { t } = useTranslation("common");
  // Opening on the preview is a way to *read* what is there, so it only makes
  // sense once there is something to read: an empty field — or one whose text
  // has not loaded yet — opens ready to type and settles on the caller's
  // default when the text arrives. A tab the reader picks themselves stands,
  // and so does the one they are typing in.
  const [chosenMode, setChosenMode] = useState<ComposerMode | null>(null);
  const mode: ComposerMode =
    chosenMode ?? (defaultMode === "preview" && !value.trim() ? "write" : defaultMode);
  const innerRef = useRef<HTMLTextAreaElement>(null);
  // Where the caret goes once the edited text has rendered. Applying it in an
  // effect rather than straight after `onChange` is what keeps it correct: the
  // field still holds the old text until the owner re-renders with the new.
  const pendingSelection = useRef<[number, number] | null>(null);

  const assignRef = useCallback(
    (node: HTMLTextAreaElement | null) => {
      innerRef.current = node;
      if (textareaRef) textareaRef.current = node;
    },
    [textareaRef]
  );

  useEffect(() => {
    const field = innerRef.current;
    const pending = pendingSelection.current;
    if (!field || !pending) return;
    pendingSelection.current = null;
    field.focus();
    field.setSelectionRange(pending[0], pending[1]);
  });

  /** Put the edited text in, and the caret where the edit says it goes. */
  const commit = useCallback(
    (next: MarkdownSelection) => {
      pendingSelection.current = [next.start, next.end];
      setChosenMode((chosen) => chosen ?? "write");
      onChange(next.value);
    },
    [onChange]
  );

  const apply = useCallback(
    (transform: MarkdownTransform) => {
      const field = innerRef.current;
      if (!field || disabled) return;
      const state: MarkdownSelection = {
        value,
        start: field.selectionStart,
        end: field.selectionEnd,
      };
      commit(transform(state));
    },
    [commit, disabled, value]
  );

  // The text as it stands now, for an upload finishing after renders that
  // came since it started — its placeholder has to be found in *that* text.
  const latestValue = useRef(value);
  latestValue.current = value;
  const uploadCount = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);

  /** Put a picture where the caret is: a placeholder at once, the picture
   *  when it has been stored, and nothing at all if it could not be. */
  const insertImages = useCallback(
    (files: File[]) => {
      const field = innerRef.current;
      if (!onUploadImage || !field || disabled || files.length === 0) return;
      const placeholders = files.map((file) => {
        uploadCount.current += 1;
        return {
          file,
          text: `![${t("markdownEditor.uploadingImage", {
            name: file.name.replace(/[[\]()]/g, ""),
          })}](uploading:${uploadCount.current})`,
        };
      });
      const start = field.selectionStart;
      const end = field.selectionEnd;
      const before = value.slice(0, start);
      // A picture is a block of its own, so it starts on a fresh line.
      const lead = before === "" || before.endsWith("\n") ? "" : "\n";
      const written = lead + placeholders.map((p) => p.text).join("\n");
      const caret = start + written.length;
      const withPlaceholders = before + written + value.slice(end);
      // Known now rather than at the next render: an upload that finishes
      // first has to find its placeholder in this text, not the one before it.
      latestValue.current = withPlaceholders;
      commit({ value: withPlaceholders, start: caret, end: caret });

      const settle = (text: string, replacement: string) => {
        const next = latestValue.current.replace(text, replacement);
        latestValue.current = next;
        onChange(next);
      };
      for (const { file, text } of placeholders) {
        onUploadImage(file).then(
          (url) => settle(text, imageMarkdown(file.name, url)),
          (error: unknown) => {
            settle(text, "");
            toast.error(getErrorMessage(error, "common:markdownEditor.imageUploadFailed"));
          }
        );
      }
    },
    [commit, disabled, onChange, onUploadImage, t, value]
  );

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!onUploadImage) return;
    const files = imagesIn(event.clipboardData);
    if (files.length === 0) return;
    event.preventDefault();
    insertImages(files);
  };

  const handleDrop = (event: DragEvent<HTMLTextAreaElement>) => {
    if (!onUploadImage) return;
    const files = imagesIn(event.dataTransfer);
    if (files.length === 0) return;
    event.preventDefault();
    insertImages(files);
  };

  const handleChosen = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // Cleared so choosing the same picture twice in a row still fires.
    event.target.value = "";
    insertImages(files);
  };

  const { capture } = usePhotoCapture((file) => insertImages([file]));

  // Paste and drop need a keyboard and a pointer; the button is how a phone
  // gets a picture in — and on the app it offers the camera first, as every
  // other picture control there does.
  const allTools = useMemo<ToolbarItem[] | undefined>(() => {
    if (!onUploadImage) return tools;
    const chooseFile = () => fileInput.current?.click();
    return [
      ...(tools ?? []),
      {
        id: "image",
        label: t("markdownEditor.image"),
        icon: ImagePlus,
        onClick: chooseFile,
        choices: canCapturePhoto()
          ? [
              {
                id: "camera",
                label: t("imagePicker.takePhoto"),
                icon: Camera,
                onSelect: () => void capture("camera"),
              },
              {
                id: "library",
                label: t("imagePicker.chooseFromLibrary"),
                icon: Images,
                onSelect: () => void capture("library"),
              },
            ]
          : undefined,
      },
    ];
  }, [capture, onUploadImage, t, tools]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    onKeyDown?.(event);
    // Anything that claimed the key first — a mention picker taking Enter,
    // the field's own submit — has already said so.
    if (event.defaultPrevented) return;

    const field = innerRef.current;
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      field
    ) {
      const carried = continueList({
        value,
        start: field.selectionStart,
        end: field.selectionEnd,
      });
      if (carried) {
        event.preventDefault();
        commit(carried);
      }
      return;
    }

    if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
    const transform = MARKDOWN_SHORTCUTS[event.key.toLowerCase()];
    if (!transform) return;
    event.preventDefault();
    apply(transform);
  };

  // A box ticked in the preview edits the text, but leaves the reader there.
  const tick = disabled ? undefined : onChange;
  const preview = renderPreview ? (
    renderPreview(value, tick)
  ) : (
    <Markdown content={value} onChange={tick} />
  );
  // Nothing in the toolbar acts on text that is not on screen.
  const toolbarDisabled = disabled || mode === "preview";

  return (
    <Tabs
      value={mode}
      onValueChange={(next) => setChosenMode(next as ComposerMode)}
      className={cn(
        "rounded-md border border-input bg-transparent shadow-sm focus-within:ring-1 focus-within:ring-ring",
        className
      )}
    >
      {/* One row that never wraps: the tabs and any action keep their size and
          the toolbar takes what is left, shedding buttons into its own menu
          rather than pushing the field down the screen. */}
      <div className="flex items-center gap-2 border-input border-b px-2 py-1.5">
        <TabsList className="h-8 shrink-0">
          <TabsTrigger value="write" className="text-xs">
            {t("markdownEditor.write")}
          </TabsTrigger>
          <TabsTrigger value="preview" className="text-xs">
            {t("markdownEditor.preview")}
          </TabsTrigger>
        </TabsList>
        <MarkdownToolbar
          onApply={apply}
          disabled={toolbarDisabled}
          className="min-w-0 flex-1"
          tools={allTools}
        />
        {actions && <div className="shrink-0">{actions}</div>}
      </div>

      {/* Kept mounted so switching tabs doesn't throw away the caret, the
          scroll position, or a mention being typed — but `forceMount` alone
          also keeps it *shown*, so the panel is hidden explicitly. */}
      <TabsContent value="write" forceMount hidden={mode !== "write"} className="mt-0">
        <div className="relative">
          <Textarea
            id={id}
            ref={assignRef}
            value={value}
            onChange={(event) => {
              setChosenMode((chosen) => chosen ?? "write");
              onChange(event.target.value);
            }}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            onDrop={handleDrop}
            onSelect={onSelect}
            onBlur={onBlur}
            placeholder={placeholder}
            rows={rows ?? (compact ? 3 : 6)}
            maxLength={maxLength}
            disabled={disabled}
            autoFocus={autoFocus}
            className="resize-y rounded-none rounded-b-md border-0 shadow-none focus-visible:ring-0"
          />
          {overlay}
          {onUploadImage && (
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              multiple
              hidden
              tabIndex={-1}
              aria-hidden
              onChange={handleChosen}
            />
          )}
        </div>
      </TabsContent>

      <TabsContent value="preview" className="mt-0">
        <div
          className={cn(
            "overflow-x-auto px-3 py-2",
            compact ? "min-h-16" : "min-h-24",
            !value.trim() && "text-muted-foreground text-sm italic"
          )}
        >
          {value.trim() ? preview : t("markdownEditor.nothingToPreview")}
        </div>
      </TabsContent>
    </Tabs>
  );
};

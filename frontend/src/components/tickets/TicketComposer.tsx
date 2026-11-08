/**
 * The box a ticket, a report or a reply is written in, with the files that go
 * with it inside the box: a paperclip to choose them, and the box itself to
 * paste or drop them on.
 *
 * Choosing is held to what the stream takes — how many, how large, of which
 * kinds — so a refusal is said before anything is sent; the server still reads
 * every file for itself. A stream that takes no files gets the box alone.
 */
import { FileText, Paperclip, X } from "lucide-react";
import {
  type ClipboardEvent,
  type ComponentProps,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { EvidencePolicyRead } from "@/api/generated/initiativeAPI.schemas";
import { isPicture } from "@/components/tickets/Evidence";
import { Button } from "@/ui/button";
import { DropOverlay } from "@/ui/file-drop";
import { formatBytes } from "@/ui/lib/fileUtils";
import { useFileDrop } from "@/ui/lib/useFileDrop";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/**
 * Whether the stream may take ``file``, as far as the browser can tell. An
 * unnamed type is left to the server, which reads the bytes; any text is
 * taken as text, as the server takes it.
 */
const mayTake = (file: File, types: string[]) =>
  !file.type ||
  types.includes(file.type) ||
  (file.type.startsWith("text/") && types.includes("text/plain"));

/** What the file chooser offers: the stream's types, and any text where it takes text. */
const acceptFor = (types: string[]) =>
  (types.includes("text/plain") ? [...types, "text/*"] : types).join(",");

/** One chosen file, told apart from the rest without its place in the list. */
const fileKey = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;

type TicketComposerProps = Omit<ComponentProps<typeof Textarea>, "className"> & {
  /** What the stream takes. No files are offered while it is not known, or
   *  where it takes none. */
  policy: EvidencePolicyRead | null | undefined;
  files: File[];
  onFilesChange: (files: File[]) => void;
};

/** Write, and attach files, in one box. */
export const TicketComposer = ({
  policy,
  files,
  onFilesChange,
  disabled,
  ...textarea
}: TicketComposerProps) => {
  const { t } = useTranslation("intake");
  const input = useRef<HTMLInputElement>(null);
  const limitsId = useId();
  const [refusal, setRefusal] = useState<string | null>(null);
  const takes = Boolean(policy && policy.max_files > 0);
  const taking = takes && !disabled;

  const add = (chosen: File[]) => {
    if (!policy) return;
    const next = [...files];
    let said: string | null = null;
    for (const file of chosen) {
      if (next.some((held) => fileKey(held) === fileKey(file))) {
        // Chosen twice: it is sent once.
      } else if (!mayTake(file, policy.types)) {
        said = t("evidence.notAllowed", { name: file.name });
      } else if (file.size > policy.max_bytes) {
        said = t("evidence.tooLarge", { name: file.name, size: formatBytes(policy.max_bytes, 0) });
      } else if (next.length >= policy.max_files) {
        said = t("evidence.tooMany", { count: policy.max_files });
      } else {
        next.push(file);
      }
    }
    setRefusal(said);
    onFilesChange(next);
    // The same file can be chosen again after it is taken back out.
    if (input.current) input.current.value = "";
  };

  const drop = useFileDrop(taking, add);
  // A pasted screenshot is attached; pasted text is written as usual.
  const onPaste = (event: ClipboardEvent) => {
    const pasted = Array.from(event.clipboardData.files);
    if (!taking || pasted.length === 0) return;
    event.preventDefault();
    add(pasted);
  };
  const limits = policy
    ? t("evidence.limits", { count: policy.max_files, size: formatBytes(policy.max_bytes, 0) })
    : "";

  return (
    <div className="space-y-1.5">
      <div
        {...drop.handlers}
        onPaste={onPaste}
        className={cn(
          "relative rounded-md border border-input shadow-sm focus-within:ring-1 focus-within:ring-ring",
          disabled && "opacity-50"
        )}
      >
        <Textarea
          {...textarea}
          disabled={disabled}
          className="resize-none rounded-b-none border-0 shadow-none focus-visible:ring-0 disabled:opacity-100"
        />
        {files.length > 0 ? (
          <ul className="flex flex-wrap gap-2.5 px-3 pt-1 pb-0.5">
            {files.map((file, index) => (
              <FileTile
                key={fileKey(file)}
                file={file}
                disabled={disabled}
                onRemove={() => {
                  setRefusal(null);
                  onFilesChange(files.filter((_, i) => i !== index));
                }}
              />
            ))}
          </ul>
        ) : null}
        {takes && policy ? (
          <div className="flex items-center gap-0.5 px-1.5 pb-1.5">
            <input
              ref={input}
              type="file"
              multiple
              className="sr-only"
              accept={acceptFor(policy.types)}
              onChange={(event) => add(Array.from(event.target.files ?? []))}
              disabled={disabled}
              data-testid="evidence-input"
              tabIndex={-1}
            />
            {/* Its own provider: there is none at the app root. */}
            <TooltipProvider delayDuration={300}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    disabled={disabled || files.length >= policy.max_files}
                    onClick={() => input.current?.click()}
                    aria-label={t("evidence.attach")}
                    aria-describedby={limitsId}
                  >
                    <Paperclip aria-hidden="true" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-56">
                  <span className="block font-medium">{t("evidence.attach")}</span>
                  <span id={limitsId}>{limits}</span>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        ) : null}
        {drop.dragging ? (
          <DropOverlay label={t("evidence.dropHere")} icon={Paperclip} className="rounded-md" />
        ) : null}
      </div>
      {refusal ? (
        <p className="text-destructive text-xs" role="alert">
          {refusal}
        </p>
      ) : null}
    </div>
  );
};

/** One attached file: a picture as itself, anything else by its name. */
const FileTile = ({
  file,
  disabled,
  onRemove,
}: {
  file: File;
  disabled?: boolean;
  onRemove: () => void;
}) => {
  const { t } = useTranslation("intake");
  const picture = isPicture(file.type);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!picture) return;
    const made = URL.createObjectURL(file);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [file, picture]);

  return (
    <li className="relative" title={file.name}>
      {picture ? (
        <img
          src={url ?? undefined}
          alt={file.name}
          className="h-12 w-auto max-w-24 rounded border bg-muted object-cover"
        />
      ) : (
        <span className="flex h-12 max-w-40 items-center gap-1.5 rounded border bg-muted/40 px-2 text-xs">
          <FileText className="size-4 shrink-0" aria-hidden="true" />
          <span className="truncate">{file.name}</span>
        </span>
      )}
      <Button
        type="button"
        variant="secondary"
        size="icon"
        className="absolute -top-2 -right-2 size-5 rounded-full border shadow-sm"
        disabled={disabled}
        aria-label={t("evidence.remove", { name: file.name })}
        onClick={onRemove}
      >
        <X className="size-3" aria-hidden="true" />
      </Button>
    </li>
  );
};

/**
 * Files a person attaches to a ticket or a report, and showing them again.
 *
 * Choosing is held to what the stream takes — how many, how large, of which
 * kinds — so a refusal is said before anything is sent; the server still
 * reads every file for itself. Each stored file is fetched by its own route,
 * which checks the reader against the file's row every time, so nothing here
 * keeps a link that outlives their access.
 */
import { Download, Eye, FileText, Paperclip, X } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EvidencePolicyRead, EvidenceRead } from "@/api/generated/initiativeAPI.schemas";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { formatBytes } from "@/ui/lib/fileUtils";
import { cn } from "@/ui/lib/utils";
import { Lightbox } from "@/ui/lightbox";

/** Pictures the browser shows in place; anything else is a download. */
const SHOWN_IN_PLACE = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

export const isPicture = (contentType: string) => SHOWN_IN_PLACE.has(contentType);

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

/** The chosen files a policy still takes, in the order they were chosen, and
 *  those it no longer does — for a form whose policy changed under them. */
export const fitToPolicy = (
  files: File[],
  policy: EvidencePolicyRead
): { kept: File[]; dropped: File[] } => {
  const kept: File[] = [];
  const dropped: File[] = [];
  for (const file of files) {
    if (
      mayTake(file, policy.types) &&
      file.size <= policy.max_bytes &&
      kept.length < policy.max_files
    ) {
      kept.push(file);
    } else {
      dropped.push(file);
    }
  }
  return { kept, dropped };
};

/** Where a file the reader filed is fetched from. */
export const filedEvidenceUrl = (taskId: number, evidenceId: number) =>
  resolveHeaderlessApiUrl(`/api/v1/me/tickets/${taskId}/evidence/${evidenceId}`);

/** Where a file in a community is fetched from, by the people working it. */
export const communityEvidenceUrl = (communityId: number, evidenceId: number) =>
  resolveHeaderlessApiUrl(`/api/v1/c/${communityId}/evidence/${evidenceId}`);

interface EvidencePickerProps {
  /** What the stream takes. Nothing to choose while it is not known. */
  policy: EvidencePolicyRead | null | undefined;
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}

/** Choose files to send, held to what the stream takes. */
export const EvidencePicker = ({ policy, files, onChange, disabled }: EvidencePickerProps) => {
  const { t } = useTranslation("intake");
  const input = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [refusal, setRefusal] = useState<string | null>(null);

  if (!policy || policy.max_files <= 0) return null;
  const size = formatBytes(policy.max_bytes, 0);

  const add = (chosen: FileList | null) => {
    if (!chosen) return;
    const next = [...files];
    let said: string | null = null;
    for (const file of Array.from(chosen)) {
      if (next.some((held) => fileKey(held) === fileKey(file))) {
        // Chosen twice: it is sent once.
      } else if (!mayTake(file, policy.types)) {
        said = t("evidence.notAllowed", { name: file.name });
      } else if (file.size > policy.max_bytes) {
        said = t("evidence.tooLarge", { name: file.name, size });
      } else if (next.length >= policy.max_files) {
        said = t("evidence.tooMany", { count: policy.max_files });
      } else {
        next.push(file);
      }
    }
    setRefusal(said);
    onChange(next);
    // The same file can be chosen again after it is taken back out.
    if (input.current) input.current.value = "";
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          type="file"
          multiple
          className="sr-only"
          accept={acceptFor(policy.types)}
          onChange={(event) => add(event.target.files)}
          disabled={disabled}
          aria-describedby={hintId}
          data-testid="evidence-input"
          tabIndex={-1}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || files.length >= policy.max_files}
          onClick={() => input.current?.click()}
        >
          <Paperclip className="h-4 w-4" aria-hidden="true" />
          {t("evidence.attach")}
        </Button>
        <span id={hintId} className="text-muted-foreground text-xs">
          {t("evidence.limits", { count: policy.max_files, size })}
        </span>
      </div>
      {files.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {files.map((file, index) => (
            <li
              key={fileKey(file)}
              className="flex max-w-full items-center gap-1 rounded-md border bg-muted/40 py-0.5 pr-1 pl-2 text-xs"
            >
              <span className="truncate">{file.name}</span>
              <span className="shrink-0 text-muted-foreground">{formatBytes(file.size)}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                disabled={disabled}
                aria-label={t("evidence.remove", { name: file.name })}
                onClick={() => {
                  setRefusal(null);
                  onChange(files.filter((_, i) => i !== index));
                }}
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {refusal ? (
        <p className="text-destructive text-xs" role="alert">
          {refusal}
        </p>
      ) : null}
    </div>
  );
};

/** One picture's thumbnail: blurred until the reader chooses to look, and
 *  opened full size either way. */
const Thumbnail = ({
  item,
  url,
  seen,
  onOpen,
}: {
  item: EvidenceRead;
  url: string;
  seen: boolean;
  onOpen: () => void;
}) => {
  const { t } = useTranslation("intake");
  return (
    <button
      type="button"
      onClick={onOpen}
      className="relative block h-24 w-24 overflow-hidden rounded-md border bg-muted"
      aria-label={
        seen
          ? t("evidence.view", { name: item.display_name })
          : t("evidence.reveal", { name: item.display_name })
      }
      title={item.display_name}
    >
      <img
        src={url}
        alt=""
        className={cn("h-full w-full object-cover", !seen && "scale-110 blur-xl")}
        loading="lazy"
      />
      {seen ? null : (
        <span className="absolute inset-0 flex items-center justify-center bg-background/30 text-foreground">
          <Eye className="h-5 w-5" aria-hidden="true" />
        </span>
      )}
    </button>
  );
};

interface EvidenceListProps {
  items: EvidenceRead[];
  urlFor: (evidenceId: number) => string;
  /** Pictures start blurred: for the people reading what somebody else sent. */
  blurred?: boolean;
  className?: string;
}

/** Files that came with something, each fetched through its own row. */
export const EvidenceList = ({ items, urlFor, blurred = false, className }: EvidenceListProps) => {
  const { t } = useTranslation("intake");
  // The pictures the reader has looked at, which stay unblurred after. Paging
  // to one in the lightbox is looking at it.
  const [seen, setSeen] = useState<ReadonlySet<number>>(new Set());
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);

  if (items.length === 0) return null;
  const pictures = items.filter((item) => isPicture(item.content_type));
  const others = items.filter((item) => !isPicture(item.content_type));
  const current = pictures[index];

  const show = (next: number) => {
    const picture = pictures[next];
    if (!picture) return;
    setIndex(next);
    setSeen((prev) => (prev.has(picture.id) ? prev : new Set(prev).add(picture.id)));
  };

  return (
    <div className={cn("space-y-2", className)}>
      {pictures.length > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label={t("evidence.heading")}>
          {pictures.map((item, i) => (
            <li key={item.id}>
              <Thumbnail
                item={item}
                url={urlFor(item.id)}
                seen={!blurred || seen.has(item.id)}
                onOpen={() => {
                  show(i);
                  setOpen(true);
                }}
              />
            </li>
          ))}
        </ul>
      ) : null}
      {pictures.length > 0 ? (
        <Lightbox
          open={open}
          onOpenChange={setOpen}
          items={pictures.map((item) => ({
            id: item.id,
            src: urlFor(item.id),
            alt: item.display_name,
            caption: item.display_name,
          }))}
          index={index}
          onIndexChange={show}
          actions={
            current ? (
              <Button
                asChild
                variant="ghost"
                size="icon"
                className="text-white hover:bg-white/10 hover:text-white"
              >
                <a
                  href={urlFor(current.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t("evidence.open", { name: current.display_name })}
                >
                  <Download className="size-5" aria-hidden="true" />
                </a>
              </Button>
            ) : null
          }
        />
      ) : null}
      {others.length > 0 ? (
        <ul className="space-y-1">
          {others.map((item) => (
            <li key={item.id}>
              <a
                href={urlFor(item.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex max-w-full items-center gap-1.5 text-sm underline-offset-2 hover:underline"
                aria-label={t("evidence.open", { name: item.display_name })}
              >
                <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{item.display_name}</span>
                <span className="shrink-0 text-muted-foreground text-xs">
                  {formatBytes(item.size_bytes)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
};

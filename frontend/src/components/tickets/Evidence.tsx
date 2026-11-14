/**
 * Showing the files that came with a ticket or a report. Choosing them is the
 * box they are written in (`TicketComposer`).
 *
 * Each stored file is fetched by its own route, which checks the reader against
 * the file's row every time, so nothing here keeps a link that outlives their
 * access.
 */
import { Download, Eye, FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { EvidenceRead } from "@/api/generated/initiativeAPI.schemas";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { formatBytes } from "@/ui/lib/fileUtils";
import { cn } from "@/ui/lib/utils";
import { Lightbox } from "@/ui/lightbox";

/** Pictures the browser shows in place; anything else is a download. */
const SHOWN_IN_PLACE = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

export const isPicture = (contentType: string) => SHOWN_IN_PLACE.has(contentType);

/** Where a file the reader filed is fetched from. */
export const filedEvidenceUrl = (taskId: number, evidenceId: number) =>
  resolveHeaderlessApiUrl(`/api/v1/me/tickets/${taskId}/evidence/${evidenceId}`);

/** Where a file in a community is fetched from, by the people working it. */
export const communityEvidenceUrl = (communityId: number, evidenceId: number) =>
  resolveHeaderlessApiUrl(`/api/v1/c/${communityId}/evidence/${evidenceId}`);

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

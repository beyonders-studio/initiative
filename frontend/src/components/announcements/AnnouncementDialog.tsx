import {
  ChevronLeft,
  ChevronRight,
  Gift,
  Megaphone,
  Rocket,
  ShieldAlert,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AnnouncementCategory,
  AnnouncementSection,
} from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import { Lightbox } from "@/components/shared/Lightbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { splitIntoPages } from "@/lib/announcementPages";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";

const CATEGORY_ICON: Record<AnnouncementCategory, typeof Megaphone> = {
  release: Rocket,
  feature: Gift,
  breaking: TriangleAlert,
  maintenance: Wrench,
  security: ShieldAlert,
  info: Megaphone,
};

interface AnnouncementDialogProps {
  open: boolean;
  title: string;
  category: AnnouncementCategory;
  sections: AnnouncementSection[];
  /**
   * The actions this announcement ends on. Shown on the last page only — a
   * wizard's "Got it" belongs after the reader has seen the whole thing, and
   * the pager gets them there.
   */
  footer?: ReactNode;
  /** Shown beside the category badge, e.g. "2 more". */
  meta?: string;
  onOpenChange: (open: boolean) => void;
}

/**
 * The one surface every announcement is shown through.
 *
 * It knows nothing about where its content came from: a notice an operator
 * wrote, one compiled into the app, or the client-side "a new version is
 * running on the server" prompt all render here, and differ only in the
 * actions their footer offers.
 *
 * Sections marked `starts_page` turn it into a pager, which is the whole of
 * the wizard shape: several beats, one at a time, in order.
 */
export const AnnouncementDialog = ({
  open,
  title,
  category,
  sections,
  footer,
  meta,
  onOpenChange,
}: AnnouncementDialogProps) => {
  const { t } = useTranslation("announcements");
  const Icon = CATEGORY_ICON[category] ?? Megaphone;

  const pages = useMemo(() => splitIntoPages(sections), [sections]);
  const [pageIndex, setPageIndex] = useState(0);
  const [zoomed, setZoomed] = useState<{ src: string; alt: string } | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // A dialog opening is a fresh read, and so is a different announcement
  // arriving in the same dialog — both start at page one. The title stands in
  // for "which announcement": the pages themselves are a fresh array each
  // render, so they cannot be what is compared.
  const [prev, setPrev] = useState({ open, title });
  if (prev.open !== open || prev.title !== title) {
    setPrev({ open, title });
    setPageIndex(0);
  }

  const safeIndex = Math.min(pageIndex, Math.max(pages.length - 1, 0));
  const isLastPage = safeIndex >= pages.length - 1;
  const goTo = (index: number) => {
    setPageIndex(index);
    // A new page starts at its top. Assigning scrollTop rather than calling
    // scrollTo: the latter is not implemented in jsdom, and there is nothing
    // to animate here anyway.
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0 space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="gap-1.5">
              <Icon className="h-3.5 w-3.5" />
              {t(`category.${category}`)}
            </Badge>
            {meta ? <span className="text-muted-foreground text-xs">{meta}</span> : null}
          </div>
          <DialogTitle>{title}</DialogTitle>
          {/* Radix wants every dialog described; the category is what the
              badge says visually, so a screen reader gets the same. */}
          <DialogDescription className="sr-only">{t(`category.${category}`)}</DialogDescription>
        </DialogHeader>

        {/* A plain overflow container rather than ScrollArea: the dialog is
            bounded by max-height, and Radix's viewport sizes itself with
            ``h-full``, which resolves to nothing against an indefinite height
            — the content would be clipped instead of scrolled. */}
        <div ref={bodyRef} className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
          <div className="space-y-6 py-4">
            {(pages[safeIndex] ?? []).map((section, index) => (
              <AnnouncementSectionView
                // Sections have no identity of their own — they are an ordered
                // list edited and saved whole — so position is the key.
                // biome-ignore lint/suspicious/noArrayIndexKey: positional by nature
                key={index}
                section={section}
                onZoom={setZoomed}
              />
            ))}
          </div>
        </div>

        {pages.length > 1 || footer ? (
          <DialogFooter className="shrink-0 border-t pt-4 sm:items-center">
            {pages.length > 1 ? (
              <div className="flex items-center gap-2 sm:mr-auto">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={safeIndex === 0}
                  onClick={() => goTo(safeIndex - 1)}
                >
                  <ChevronLeft className="h-4 w-4" />
                  {t("dialog.back")}
                </Button>
                <span className="text-muted-foreground text-xs">
                  {t("dialog.pageOf", { current: safeIndex + 1, total: pages.length })}
                </span>
              </div>
            ) : null}
            {isLastPage ? (
              footer
            ) : (
              <Button onClick={() => goTo(safeIndex + 1)}>
                {t("dialog.continue")}
                <ChevronRight className="h-4 w-4" />
              </Button>
            )}
          </DialogFooter>
        ) : null}
      </DialogContent>

      {/* Nested on purpose: Escape and a click outside close the picture and
          leave the announcement where it was, rather than dismissing it. */}
      <Lightbox
        open={zoomed !== null}
        onOpenChange={(next) => !next && setZoomed(null)}
        items={zoomed ? [{ id: zoomed.src, src: zoomed.src, alt: zoomed.alt || title }] : []}
        index={0}
        onIndexChange={() => {}}
      />
    </Dialog>
  );
};

const AnnouncementSectionView = ({
  section,
  onZoom,
}: {
  section: AnnouncementSection;
  onZoom: (image: { src: string; alt: string }) => void;
}) => {
  const { t } = useTranslation("announcements");
  const imageSrc = section.image_url
    ? section.image_url.startsWith("/api/")
      ? resolveHeaderlessApiUrl(section.image_url)
      : section.image_url
    : null;

  return (
    <section className="space-y-3">
      {section.heading ? <h3 className="font-semibold text-base">{section.heading}</h3> : null}
      {section.body ? <Markdown remoteImages content={section.body} /> : null}
      {imageSrc ? (
        // A screenshot shrunk into a dialog is often unreadable, so it opens
        // at full size on click.
        <button
          type="button"
          className="block w-full cursor-zoom-in rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t("dialog.zoomImage")}
          onClick={() => onZoom({ src: imageSrc, alt: section.image_alt ?? "" })}
        >
          <img
            src={imageSrc}
            alt={section.image_alt ?? ""}
            loading="lazy"
            className="w-full rounded-md border bg-muted"
          />
        </button>
      ) : null}
    </section>
  );
};

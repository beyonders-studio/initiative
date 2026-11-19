/**
 * A listing's pictures, as a store shows them: a row of large screenshots under
 * its name, each opening full size in the lightbox, where it zooms.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/ui/carousel";
import { Lightbox, type LightboxItem } from "@/ui/lightbox";

export function ListingGallery({ name, sources }: { name: string; sources: string[] }) {
  const { t } = useTranslation("marketplace");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const items: LightboxItem[] = sources.map((src, at) => ({
    id: src,
    src,
    alt: t("detail.screenshot", { name, number: at + 1 }),
  }));

  return (
    <section className="space-y-3" aria-labelledby="listing-screenshots">
      <h2 id="listing-screenshots" className="font-medium text-sm">
        {t("detail.screenshots")}
      </h2>
      <Carousel>
        <CarouselContent className="-ml-4">
          {items.map((item, at) => (
            <CarouselItem key={item.id} className="max-w-full basis-auto pl-4">
              <button
                type="button"
                className="block cursor-zoom-in overflow-hidden rounded-xl border bg-muted shadow-sm transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  setIndex(at);
                  setOpen(true);
                }}
              >
                <img
                  src={item.src}
                  alt={item.alt}
                  className="h-64 w-auto max-w-[min(90vw,48rem)] object-cover sm:h-80"
                  loading="lazy"
                />
              </button>
            </CarouselItem>
          ))}
        </CarouselContent>
        <CarouselPrevious />
        <CarouselNext />
      </Carousel>
      <Lightbox
        open={open}
        onOpenChange={setOpen}
        items={items}
        index={index}
        onIndexChange={setIndex}
      />
    </section>
  );
}

/**
 * A listing's long description: paragraphs split by a blank line, and a
 * paragraph whose every line starts with "- " drawn as a list.
 */
export function ListingDescription({ text }: { text: string }) {
  const blocks = text
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  return (
    <div className="max-w-3xl space-y-3 text-sm leading-relaxed">
      {blocks.map((block, at) => {
        const lines = block.split("\n");
        return lines.every((line) => line.startsWith("- ")) ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks are fixed text, never reordered
          <ul key={at} className="list-disc space-y-1 pl-5">
            {lines.map((line) => (
              <li key={line}>{line.slice(2)}</li>
            ))}
          </ul>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks are fixed text, never reordered
          <p key={at} className="whitespace-pre-line">
            {block}
          </p>
        );
      })}
    </div>
  );
}

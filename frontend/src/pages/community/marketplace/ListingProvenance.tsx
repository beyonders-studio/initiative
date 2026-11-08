/**
 * Who publishes a listing.
 *
 * One name, required of every listing, shown wherever a listing is: the cards,
 * the detail page, and both install dialogs — so the question is answered at
 * the moment of the decision rather than only on the page someone may not have
 * opened.
 *
 * Deliberately not a trust ranking. Every listing on a deployment is there
 * because whoever runs the server put it there — they choose the registry to trust and
 * the files to drop in — so sorting listings by where they came from would
 * imply a distinction the platform does not have. What keeps the name honest is
 * enforcement rather than a badge: `core.*` is reserved to listings shipped in
 * this repository, and a registry's index is signature-checked against a
 * configured key before any listing in it is read.
 */

import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

/**
 * The fields the byline reads. Structural rather than the generated summary
 * type, so a browse card, a detail page and a dialog all satisfy it.
 */
export interface ListingAttribution {
  source: string;
  publisher: string;
}

export interface ListingProvenanceProps {
  listing: ListingAttribution;
  className?: string;
}

export function ListingProvenance({ listing, className }: ListingProvenanceProps) {
  const { t } = useTranslation("marketplace");

  // Listings shipped in this repository are credited to us rather than to
  // whatever their manifest says, since `core.*` is reserved to them.
  const line =
    listing.source === "builtin"
      ? t("provenance.builtin")
      : t("provenance.plain", { publisher: listing.publisher });

  return <p className={cn("text-muted-foreground text-xs", className)}>{line}</p>;
}

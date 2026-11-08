/**
 * The user guide's search index, for the Help panel.
 *
 * Published beside the user guide when it deploys
 * (`backend/scripts/build_help_index.py`), so every server searches the same
 * pages its links open. Read once a session: the guide changes only when it is
 * published.
 */

import { useQuery } from "@tanstack/react-query";

import type { HelpIndexEntry } from "@/lib/helpSearch";
import { DOCS_SITE_URL } from "@/lib/links";

export const HELP_INDEX_URL = `${DOCS_SITE_URL}help-index.json`;

const FIELDS = ["title", "section", "location", "snippet"] as const;

const isEntry = (item: unknown): item is HelpIndexEntry =>
  typeof item === "object" &&
  item !== null &&
  FIELDS.every((field) => typeof (item as Record<string, unknown>)[field] === "string");

const fetchHelpIndex = async (): Promise<HelpIndexEntry[]> => {
  // The docs site needn't learn which server asked.
  const response = await fetch(HELP_INDEX_URL, { referrerPolicy: "no-referrer" });
  if (!response.ok) throw new Error(`help index: HTTP ${response.status}`);
  const items = ((await response.json()) as { items?: unknown } | null)?.items;
  return Array.isArray(items) ? items.filter(isEntry) : [];
};

/** Every page and heading of the user guide, in the guide's order. */
export const useHelpIndex = () =>
  useQuery({
    queryKey: ["help-index"],
    queryFn: fetchHelpIndex,
    staleTime: Number.POSITIVE_INFINITY,
  });

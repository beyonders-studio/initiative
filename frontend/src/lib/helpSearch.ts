import { commandFilter } from "@/ui/lib/fuzzyMatch";

/** One page or heading of the user guide, as plain text. */
export interface HelpIndexEntry {
  title: string;
  /** Where it sits, the last two steps of its breadcrumb: `FAQ › Getting in`. */
  section: string;
  /** Its address from the docs site's root, with its anchor: `en/faq/#…`. */
  location: string;
  /** The start of its text, cut at a word. */
  snippet: string;
}

/**
 * What a page is about, from its route template: the last thing it names, a
 * parameter by what it holds (`$initiativeId` is an initiative). The
 * one-letter prefixes (`/c/`, `/i/`) are left out, since a parameter names it.
 */
export const pageTerm = (routeTemplate: string): string =>
  routeTemplate
    .split("/")
    .map((segment) => (segment.startsWith("$") ? segment.slice(1).replace(/Id$/, "") : segment))
    .filter((segment) => segment.length > 1)
    .at(-1) ?? "";

/** The user guide's entries that name what a page is about in their title or section. */
export const forPage = (entries: HelpIndexEntry[], routeTemplate: string): HelpIndexEntry[] => {
  const term = pageTerm(routeTemplate);
  // Named outright, which `commandFilter` scores 0.8 and up.
  return term
    ? entries.filter((entry) => commandFilter(`${entry.title} ${entry.section}`, term) >= 0.8)
    : [];
};

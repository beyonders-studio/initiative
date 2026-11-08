import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { SearchHit } from "@/api/generated/initiativeAPI.schemas";
import { MentionText } from "@/components/user/MentionText";
import { useCommunityPath } from "@/lib/communityUrl";
import { FROM_SEARCH, hitIcon, searchHitPath } from "@/lib/searchResults";

/**
 * The pieces of a snippet, with the matched words marked.
 *
 * `ts_headline` wraps what matched in `<` and `>`. Body text can contain those
 * characters itself, so an unpaired one is left as ordinary text rather than
 * swallowing the rest of the line.
 */
export function splitSnippet(snippet: string): Array<{ text: string; match: boolean }> {
  const parts: Array<{ text: string; match: boolean }> = [];
  let rest = snippet;
  while (rest.length > 0) {
    const open = rest.indexOf("<");
    const close = open === -1 ? -1 : rest.indexOf(">", open + 1);
    if (open === -1 || close === -1) {
      parts.push({ text: rest, match: false });
      break;
    }
    if (open > 0) parts.push({ text: rest.slice(0, open), match: false });
    parts.push({ text: rest.slice(open + 1, close), match: true });
    rest = rest.slice(close + 1);
  }
  return parts.filter((part) => part.text.length > 0);
}

/**
 * One result: what it is, what it is called, and the part of it that matched.
 *
 * A hit whose address can't be built renders as plain text rather than a dead
 * link — it was still found, and saying so is better than offering a link that
 * goes nowhere. A comment is shown by its opening words, and those and any
 * snippet can mention people, who read as chips inside the row's link.
 */
function SearchResultRow({ hit }: { hit: SearchHit }) {
  const { t } = useTranslation("search");
  const getCommunityPath = useCommunityPath();
  const Icon = hitIcon(hit);
  const path = searchHitPath(hit);
  const kind = t(`types.${hit.entity_type}` as never, { defaultValue: hit.entity_type });

  const body = (
    <>
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium">
            <MentionText text={hit.title} disableLink />
          </span>
          <span className="shrink-0 text-muted-foreground text-xs">{kind}</span>
        </div>
        {hit.snippet && (
          <p className="mt-0.5 line-clamp-2 text-muted-foreground text-sm">
            {splitSnippet(hit.snippet).map((part, index) =>
              part.match ? (
                // biome-ignore lint/suspicious/noArrayIndexKey: snippet pieces have no id
                <mark key={index} className="bg-transparent font-medium text-foreground">
                  {part.text}
                </mark>
              ) : (
                // biome-ignore lint/suspicious/noArrayIndexKey: snippet pieces have no id
                <span key={index}>
                  <MentionText text={part.text} disableLink />
                </span>
              )
            )}
          </p>
        )}
      </div>
    </>
  );

  if (!path) {
    return <div className="flex gap-3 rounded-md px-3 py-2">{body}</div>;
  }
  return (
    <Link
      to={getCommunityPath(path)}
      state={FROM_SEARCH}
      className="flex gap-3 rounded-md px-3 py-2 hover:bg-accent"
    >
      {body}
    </Link>
  );
}

/** A list of results. */
export function SearchResultList({ hits }: { hits: SearchHit[] }) {
  return hits.map((hit) => (
    <SearchResultRow key={`${hit.entity_type}-${hit.entity_id}`} hit={hit} />
  ));
}

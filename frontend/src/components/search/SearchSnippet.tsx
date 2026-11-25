import { MentionText } from "@/components/user/MentionText";
import { cn } from "@/ui/lib/utils";

/**
 * The pieces of a snippet, with the matched words marked.
 *
 * `ts_headline` wraps what matched in `<` and `>`. Body text can contain those
 * characters itself, so an unpaired one is left as ordinary text rather than
 * swallowing the rest of the line.
 */
function splitSnippet(snippet: string): Array<{ text: string; match: boolean }> {
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

/** Whether a snippet holds a matched word. One that does not is only the
 *  opening of the body, which says nothing about why the hit was found. */
export const snippetMatches = (snippet: string): boolean =>
  splitSnippet(snippet).some((part) => part.match);

/** The part of a search hit that matched, its matched words marked. It can
 *  mention people, who read as chips. */
export function SearchSnippet({ snippet, className }: { snippet: string; className?: string }) {
  return (
    <p className={cn("text-muted-foreground text-sm", className)}>
      {splitSnippet(snippet).map((part, index) =>
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
  );
}

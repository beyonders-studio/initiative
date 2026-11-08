import { Markdown } from "@/components/markdown/Markdown";

/**
 * One message's words, as markdown.
 *
 * The same basic formatting a comment gets — emphasis, code, lists, quotes,
 * links — and deliberately less besides. Two things are left out:
 *
 * * **Mentions.** They are read back against a community's roster, and a
 *   direct message belongs to no community. There is nothing here to resolve
 *   them against and nobody who should be asked to.
 * * **Pictures.** An image becomes a link carrying its name, so the page loads
 *   nothing of its own and the reader decides whether to follow it.
 *
 * Markdown is rendered without raw HTML, and links keep only the schemes
 * react-markdown will follow.
 */
export const MessageContent = ({ body, className }: { body: string; className?: string }) => (
  <Markdown surface="message" content={body} className={className} />
);

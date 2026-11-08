import { $createLinkNode, LinkNode } from "@lexical/link";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  createEditor,
  type ParagraphNode,
  type SerializedEditorState,
} from "lexical";

import { imageMarkdown } from "@/lib/markdownEditing";
import { RESERVED_SIGILS } from "@/lib/mentions";
import type { ReceivedShare } from "@/lib/share/pendingShare";
import { $createImageNode, ImageNode } from "@/ui/editor/nodes/image-node";

/** The backend's `MAX_TITLE_LENGTH`: the most a name or title may hold. */
const MAX_TITLE_LENGTH = 255;

// A link as people paste one: from the scheme to the next space, without the
// full stop or bracket that closes the sentence around it.
const LINK = /https?:\/\/[^\s<>"]+[^\s<>".,;:!?)\]'}]/g;

const linksIn = (text: string): string[] => text.match(LINK) ?? [];

const isOnlyALink = (line: string) => {
  const links = linksIn(line);
  return links.length === 1 && links[0] === line.trim();
};

const hostOf = (link: string): string | null => {
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
};

/**
 * A title fit to be a name: on one line, without the characters a name may not
 * carry, and no longer than a title may be. A page's title often has an `@` or a
 * `#` in it, and the server refuses a name that does.
 */
export function asTitle(text: string): string {
  let title = text;
  for (const sigil of RESERVED_SIGILS) title = title.split(sigil).join("");
  title = title.replace(/\s+/g, " ").trim();
  return title.length > MAX_TITLE_LENGTH ? title.slice(0, MAX_TITLE_LENGTH).trimEnd() : title;
}

/**
 * What the new thing is called, before anybody edits it: the title the other
 * app gave, else the first line written, else the site a link points at. A
 * share that is only pictures has none of those, and takes `fallback`.
 */
export function shareTitle(share: ReceivedShare, fallback: string): string {
  if (share.title) {
    const title = asTitle(share.title);
    if (title) return title;
  }
  for (const text of share.texts) {
    const line = text.split("\n").find((candidate) => candidate.trim() && !isOnlyALink(candidate));
    if (line) {
      const title = asTitle(line);
      if (title) return title;
    }
  }
  for (const text of share.texts) {
    const host = linksIn(text).map(hostOf).find(Boolean);
    if (host) return host;
  }
  return fallback;
}

/**
 * What goes in the body: everything written, as written. A note that says
 * exactly what the title does is left out rather than said twice; one the title
 * had to shorten or strip of a sigil keeps what the title lost.
 */
export function shareNote(share: ReceivedShare, title: string): string {
  const note = share.texts.join("\n\n").trim();
  return note === title ? "" : note;
}

/** A task's description: the note, then each picture below it. */
export function shareMarkdown(note: string, images: { name: string; url: string }[]): string {
  return [note.trim(), ...images.map((image) => imageMarkdown(image.name, image.url))]
    .filter(Boolean)
    .join("\n\n");
}

const $paragraphOf = (line: string): ParagraphNode => {
  const paragraph = $createParagraphNode();
  let from = 0;
  for (const match of line.matchAll(LINK)) {
    const at = match.index ?? 0;
    if (at > from) paragraph.append($createTextNode(line.slice(from, at)));
    const link = $createLinkNode(match[0], { rel: "noopener noreferrer", target: "_blank" });
    link.append($createTextNode(match[0]));
    paragraph.append(link);
    from = at + match[0].length;
  }
  if (from < line.length) paragraph.append($createTextNode(line.slice(from)));
  return paragraph;
};

/**
 * A document's or a post's body: a paragraph for each line of the note, its
 * links live, then each picture in a paragraph of its own — the shape the
 * editor's own insert-picture command leaves.
 *
 * Built by a headless editor holding only the nodes it writes, so the state is
 * the editor's own serialization rather than a hand-written copy of it.
 */
export function shareBody(
  note: string,
  images: { src: string; altText: string }[]
): SerializedEditorState {
  const editor = createEditor({
    namespace: "share",
    nodes: [LinkNode, ImageNode],
    onError: (error) => {
      throw error;
    },
  });
  editor.update(
    () => {
      const root = $getRoot();
      const lines = note.trim() ? note.trim().split("\n") : [];
      for (const line of lines) root.append($paragraphOf(line));
      for (const image of images) {
        const paragraph = $createParagraphNode();
        paragraph.append($createImageNode(image));
        root.append(paragraph);
      }
      if (root.getChildrenSize() === 0) root.append($createParagraphNode());
    },
    { discrete: true }
  );
  return editor.getEditorState().toJSON();
}

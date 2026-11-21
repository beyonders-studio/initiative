/**
 * The markdown passes every body in the product goes through.
 *
 * Nothing here is about comments or about messages: one turns an image into a
 * name rather than a fetch, the other treats a newline as a newline. Both are
 * wanted wherever somebody types prose into a box, so they live below the
 * surfaces that use them rather than in one of them.
 */

/** Minimal structural view of the mdast nodes these plugins touch. */
export interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  identifier?: string;
  children?: MdastNode[];
  data?: Record<string, unknown>;
  position?: { start: { offset?: number }; end: { offset?: number } };
}

/** Both spellings of an image and of a link — inline, and by reference. */
export const IMAGE_TYPES = new Set(["image", "imageReference"]);
export const LINK_TYPES = new Set(["link", "linkReference"]);

/** Walk every node that has children, parents before their children. */
export function visitParents(node: MdastNode, fn: (parent: MdastNode) => void) {
  if (!node.children) return;
  fn(node);
  for (const child of node.children) visitParents(child, fn);
}

/** Whether an address is a picture stored in this app, rather than one
 *  somewhere else on the web. */
export const isStoredUpload = (url: string): boolean => url.startsWith("/uploads/");

interface ImageLinkOptions {
  /** Images to leave as images — pictures this app stores, which a reader
   *  fetches from the server they are already talking to. */
  keep?: (url: string) => boolean;
}

/**
 * Turn an image into a link to itself, named by its alt text, so a comment
 * reports what it points at rather than fetching it. An image the author
 * already wrapped in a link contributes only its name: the wrapping link keeps
 * its own destination, and a link cannot legally hold another.
 */
export function remarkImageLinks(options: ImageLinkOptions = {}) {
  return (tree: MdastNode) => {
    // A reference-style image names a definition elsewhere in the document
    // rather than carrying its own address.
    const definitions = new Map<string, string>();
    visitParents(tree, (parent) => {
      for (const child of parent.children ?? []) {
        if (child.type === "definition" && child.identifier && child.url) {
          definitions.set(child.identifier, child.url);
        }
      }
    });

    const urlOf = (node: MdastNode) =>
      node.url ?? (node.identifier ? definitions.get(node.identifier) : undefined);

    // The wrapping link can be any number of levels up — emphasis, a heading,
    // a table cell — so this tracks the ancestry rather than the parent alone.
    const rewrite = (node: MdastNode, insideLink: boolean) => {
      const children = node.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (!IMAGE_TYPES.has(child.type)) {
          rewrite(child, insideLink || LINK_TYPES.has(child.type));
          continue;
        }

        const url = urlOf(child);
        if (url && options.keep?.(url)) continue;
        const label = child.alt || url || "";
        if (!label) {
          children.splice(i, 1);
          continue;
        }

        children[i] =
          insideLink || !url
            ? { type: "text", value: label }
            : { type: "link", url, children: [{ type: "text", value: label }] };
      }
    };

    rewrite(tree, LINK_TYPES.has(tree.type));
  };
}

/**
 * Treat a single newline as a line break, the way comment authors expect from
 * a plain textarea — markdown would otherwise join those lines into one
 * paragraph.
 */
export function remarkLineBreaks() {
  return (tree: MdastNode) => {
    visitParents(tree, (parent) => {
      const children = parent.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const child = children[i];
        if (child.type !== "text" || typeof child.value !== "string") continue;
        if (!child.value.includes("\n")) continue;

        const replacement: MdastNode[] = [];
        // A trailing space before the newline is markdown's own hard break;
        // trimming it keeps the rendered gap consistent either way.
        const segments = child.value.split("\n");
        segments.forEach((segment, index) => {
          if (index > 0) replacement.push({ type: "break" });
          const value = index < segments.length - 1 ? segment.replace(/[ \t]+$/, "") : segment;
          if (value) replacement.push({ type: "text", value });
        });

        children.splice(i, 1, ...replacement);
      }
    });
  };
}

/** Faces people type that start with `>`, which markdown would read as a quote. */
const QUOTE_FACES = [
  ">.>",
  ">.<",
  ">_>",
  ">_<",
  ">:(",
  ">:)",
  ">:D",
  ">:P",
  ">:O",
  ">:3",
  ">w<",
  ">///<",
];

/** Faces markdown would read as emphasis, strikethrough or an escape: `*_*`
 *  would be an italic `_`, and the shrug would lose an arm. */
const INLINE_FACES = [
  "¯\\_(ツ)_/¯",
  "(*^_^*)",
  "(*^▽^*)",
  "*_*",
  "*-*",
  "*.*",
  "*o*",
  "~_~",
  "~.~",
  "~-~",
];

/** What markdown may have made of a face's characters. */
const FORMATTING = new Set(["text", "emphasis", "strong", "delete"]);

/**
 * A face reads as it was typed. A quote that starts with one is the face, not
 * a quote holding `.>`; where one sits in a line, the markdown it was read as
 * goes back to the text typed. Code keeps what it holds.
 */
export function remarkFaces() {
  return (tree: MdastNode, file: { value: unknown }) => {
    const source = String(file.value);
    visitParents(tree, (parent) => {
      const children = parent.children ?? [];
      for (let i = children.length - 1; i >= 0; i--) {
        const quote = children[i];
        const start = quote.position?.start.offset;
        if (quote.type !== "blockquote" || start === undefined) continue;
        if (!QUOTE_FACES.some((face) => source.startsWith(face, start))) continue;
        const text = quote.children?.[0]?.children?.[0];
        if (text?.type !== "text") continue;
        text.value = `>${text.value}`;
        children.splice(i, 1, ...(quote.children ?? []));
      }

      const from = parent.position?.start.offset;
      const to = parent.position?.end.offset;
      if (from === undefined || to === undefined) return;
      for (const face of INLINE_FACES) {
        for (let at = source.indexOf(face, from); at !== -1 && at < to; ) {
          const end = at + face.length;
          const hit = children.flatMap((child, index) => {
            const a = child.position?.start.offset;
            const b = child.position?.end.offset;
            return a !== undefined && b !== undefined && a < end && b > at ? [index] : [];
          });
          const first = children[hit[0]];
          const last = children[hit[hit.length - 1]];
          // Only formatting is undone. A link or a paragraph looks at its own
          // children, code holds the face as typed, and so may plain text.
          const formatted =
            hit.length > 0 &&
            hit.every((index) => FORMATTING.has(children[index].type)) &&
            !(hit.length === 1 && first.value?.includes(face));
          if (formatted && first.position && last.position) {
            const position = { start: first.position.start, end: last.position.end };
            const value = source.slice(position.start.offset, position.end.offset);
            children.splice(hit[0], hit.length, { type: "text", value, position });
          }
          at = source.indexOf(face, end);
        }
      }
    });
  };
}

import type {
  ComponentProps,
  ComponentPropsWithoutRef,
  ComponentType,
  MouseEvent,
  Ref,
} from "react";
import { createContext, useContext } from "react";
import ReactMarkdown, { type ExtraProps, type Options } from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { LinkedMentionSpan, PlainMentionSpan } from "@/components/comments/MentionSpan";
import { remarkMentions } from "@/components/comments/remarkCommentPlugins";
import { ImageLightboxScope, InLink, ProseImage } from "@/components/markdown/ProseImage";
import { ThemeContext } from "@/hooks/useTheme";
import { releaseImageUrl } from "@/lib/releaseImages";
import { isStoredUpload, remarkImageLinks, remarkLineBreaks } from "@/lib/remarkProse";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

// react-markdown hands every custom component the hast `node`, which is not a
// DOM attribute — it is dropped before the rest of the props reach the element.
type AnchorProps = ComponentPropsWithoutRef<"a"> & { node?: unknown };
type ImageProps = ComponentProps<"img"> & ExtraProps;
type ParagraphProps = ComponentPropsWithoutRef<"p"> & ExtraProps;
type ListItemProps = ComponentPropsWithoutRef<"li"> & ExtraProps;
type InputProps = ComponentPropsWithoutRef<"input"> & ExtraProps;

function handleHashClick(e: MouseEvent<HTMLAnchorElement>) {
  const href = e.currentTarget.getAttribute("href");
  if (!href) return;

  // Walk up to the nearest scrollable ancestor
  let container: HTMLElement | null = e.currentTarget.parentElement;
  while (container) {
    const { overflow, overflowY } = getComputedStyle(container);
    if (
      overflow === "auto" ||
      overflow === "scroll" ||
      overflowY === "auto" ||
      overflowY === "scroll"
    ) {
      break;
    }
    container = container.parentElement;
  }

  const target = (container ?? document).querySelector(href);
  if (target) {
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

/** A link on another origin opens in a new tab and tells the far end nothing
 *  of the page it came from; a link inside the app stays in this tab. */
function MarkdownAnchor({ node: _node, href, children, ...props }: AnchorProps) {
  let elsewhere = false;
  if (href) {
    try {
      elsewhere = new URL(href, window.location.href).origin !== window.location.origin;
    } catch {
      // An address the browser cannot read is left to it, in this tab.
    }
  }
  return (
    <a
      {...props}
      href={href}
      onClick={href?.startsWith("#") ? handleHashClick : undefined}
      target={elsewhere ? "_blank" : undefined}
      rel={elsewhere ? "noopener noreferrer" : undefined}
    >
      <InLink>{children}</InLink>
    </a>
  );
}

const PlainAnchor = ({ children }: AnchorProps) => <span>{children}</span>;

/** A picture by its name — for a clamped preview, and for any image that
 *  reaches here without being one the surface draws. */
const ImageName = ({ src, alt }: ImageProps) => (
  <span>{alt || (typeof src === "string" ? src : "")}</span>
);

/** A picture stored here is addressed at the server, which on the native app is
 *  not the origin the page is served from. */
const pictureWith = (className?: string) =>
  function MarkdownImage({ src, alt, title }: ImageProps) {
    if (typeof src !== "string" || !src) return null;
    return (
      <ProseImage
        src={resolveUploadUrl(src) ?? src}
        alt={alt ?? ""}
        title={title}
        className={className}
      />
    );
  };

/** A screenshot in the release notes, in the theme the app is drawn in,
 *  loaded from the docs site (see `lib/releaseImages`). */
function ReleasePicture({
  src,
  alt,
  title,
  fill = false,
}: {
  src: string;
  alt?: string;
  title?: string;
  fill?: boolean;
}) {
  const dark = useContext(ThemeContext)?.resolvedTheme === "dark";
  return (
    <ProseImage
      src={releaseImageUrl(src, dark)}
      alt={alt ?? ""}
      title={title}
      fill={fill}
      className={fill ? undefined : "rounded-md border border-border"}
    />
  );
}

function ReleaseImage({ src, alt, title }: ImageProps) {
  if (typeof src !== "string" || !src) return null;
  return <ReleasePicture src={src} alt={alt} title={title} />;
}

/** Pictures on lines of their own, two or more, scroll sideways as a strip of
 *  tiles with their count in its corner, each opening full size. Anything
 *  else is a paragraph. */
function ReleaseParagraph({ node, children, ...props }: ParagraphProps) {
  const parts = node?.children ?? [];
  const pictures = parts.flatMap((part) =>
    part.type === "element" && part.tagName === "img" && typeof part.properties.src === "string"
      ? [{ src: part.properties.src, alt: String(part.properties.alt ?? "") }]
      : []
  );
  const onlyPictures = parts.every(
    (part) =>
      (part.type === "element" && part.tagName === "img") ||
      (part.type === "text" && !part.value.trim())
  );
  if (pictures.length < 2 || !onlyPictures) return <p {...props}>{children}</p>;
  return (
    <div className="relative">
      <div className="scrollbar-thin flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {pictures.map((picture) => (
          <div
            key={picture.src}
            className="h-40 w-64 shrink-0 snap-start overflow-hidden rounded-lg border bg-muted p-1"
          >
            <ReleasePicture {...picture} fill />
          </div>
        ))}
      </div>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute top-2 right-2 rounded-full bg-background/90 px-2 py-0.5 font-medium text-foreground text-xs shadow-sm"
      >
        {pictures.length}
      </span>
    </div>
  );
}

/** Ticks or unticks the checklist item that starts at an offset in the text. */
const TaskToggleContext = createContext<((itemStart: number) => void) | null>(null);
/** Where in the text the list item a box sits in starts. */
const ListItemStartContext = createContext<number | undefined>(undefined);

/** A list item, telling a checklist box inside it where the item starts. */
function ListItem({ node, ...props }: ListItemProps) {
  return (
    <ListItemStartContext.Provider value={node?.position?.start.offset}>
      <li {...props} />
    </ListItemStartContext.Provider>
  );
}

/** A checklist box that ticks, in text that can be changed. */
function TaskBox({ node: _node, disabled, className, ...props }: InputProps) {
  const toggle = useContext(TaskToggleContext);
  const itemStart = useContext(ListItemStartContext);
  if (props.type !== "checkbox" || !toggle || itemStart === undefined) {
    return <input {...props} className={className} disabled={disabled} />;
  }
  return (
    <input
      {...props}
      className={cn("cursor-pointer", className)}
      onChange={() => toggle(itemStart)}
    />
  );
}

/** What every surface shares. Anything that can be wider than its container
 *  is wrapped or scrolled, so rendered markdown never stretches its card. A
 *  checklist item's box sits where its bullet would. */
const BASE_CLASS =
  "[&_.task-list-item]:list-none [&_.task-list-item_input]:-ml-5 [&_.task-list-item_input]:mr-1 [&_.task-list-item_input]:align-middle wrap-break-word[&_a:hover]:underline [&_a]:break-all [&_blockquote]:border-l-2 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h4]:font-semibold [&_h6]:font-semibold [&_ol]:list-decimal [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_strong]:font-semibold [&_table]:block [&_table]:w-fit [&_table]:overflow-x-auto [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_th]:font-semibold [&_ul]:list-disc";

/** The app's own colours, for prose on a page rather than in a bubble. */
const PAGE_TONE_CLASS =
  "[&_a]:text-primary [&_blockquote]:border-muted-foreground/30 [&_code]:bg-muted [&_hr]:border-border [&_pre]:bg-muted [&_td]:border-border [&_th]:border-border";

interface Surface {
  /** Type scale and colours. */
  prose: string;
  /** Space between blocks, dropped in a compact preview. */
  spacing: string;
  /** How a picture the text keeps is drawn. `null` keeps none: every picture
   *  becomes a link carrying its name. */
  picture: ComponentType<ImageProps> | null;
  /** A single newline is a line break, as somebody typing in a textarea means it. */
  lineBreaks: boolean;
  /** Headings carry ids, so a `#heading` link scrolls to them. */
  headingIds: boolean;
  /** How a paragraph is drawn, when the surface draws some differently. */
  paragraph?: ComponentType<ParagraphProps>;
}

/** Descriptions and documents: the long form, in the page's type scale. */
const DOCUMENT = {
  prose: `${PAGE_TONE_CLASS} text-muted-foreground text-sm **:leading-relaxed [&_blockquote]:pl-3 [&_code]:font-mono [&_code]:wrap-break-word [&_h1]:text-xl [&_h2]:text-lg [&_h3]:text-base [&_h4]:text-sm [&_h5]:font-medium [&_h5]:text-sm [&_h6]:text-xs [&_img]:h-auto [&_img]:max-w-full [&_li]:mt-1 [&_ol]:pl-6 [&_pre]:max-w-full [&_pre]:whitespace-pre-wrap [&_pre]:wrap-break-word [&_pre_code]:text-inherit [&_table]:max-w-full [&_ul]:pl-6`,
  spacing: "space-y-3 [&_h1]:mt-4 [&_h2]:mt-3 [&_h3]:mt-3 [&_h4]:mt-2 [&_h5]:mt-2 [&_h6]:mt-2",
  picture: pictureWith(),
  lineBreaks: false,
  headingIds: true,
} satisfies Surface;

const SURFACES = {
  document: DOCUMENT,
  /** Release notes: a document whose pictures are screenshots that ship with
   *  the release, drawn in the app's theme. */
  release: { ...DOCUMENT, picture: ReleaseImage, paragraph: ReleaseParagraph },
  /** A comment: short prose typed in a box, headings kept to body size. */
  comment: {
    prose: `${PAGE_TONE_CLASS} text-sm [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_h4]:text-sm [&_h5]:font-semibold [&_h5]:text-sm [&_h6]:text-sm [&_li]:mt-0.5 [&_ol]:pl-5 [&_ul]:pl-5`,
    spacing: "[&>*+*]:mt-2 [&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2",
    picture: pictureWith("max-h-80 rounded-md border border-border"),
    lineBreaks: true,
    headingIds: false,
  },
  /** A direct message: drawn in the bubble's own colour, and it draws no
   *  picture, so the page loads nothing the sender chose. */
  message: {
    prose:
      "[&_a]:underline [&_blockquote]:border-current/30 [&_blockquote]:pl-2 [&_code]:bg-black/15 [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_h5]:font-semibold [&_hr]:border-current/30 [&_li]:mt-0.5 [&_ol]:pl-5 [&_pre]:bg-black/15 [&_td]:border-current/30 [&_th]:border-current/30 [&_ul]:pl-5",
    spacing: "[&>*+*]:mt-2",
    picture: null,
    lineBreaks: true,
    headingIds: false,
  },
} satisfies Record<string, Surface>;

const HEADING_ID_PLUGINS = [rehypeSlug];

interface MarkdownProps {
  content: string;
  className?: string;
  /** What kind of prose this is: its type scale and colours, which pictures
   *  it draws, and how it reads a newline. */
  surface?: keyof typeof SURFACES;
  /** Reads the mention syntax the mention composer writes — `@[Ada](4)`,
   *  `#task[Ship it](12)` — as chips rather than links to a bare number. Only
   *  prose written in that composer carries it, so it is asked for. */
  mentions?: boolean;
  /** Whether a picture opens full size on click. Off where the pictures are
   *  not shown at all, such as a clamped card preview. */
  zoomImages?: boolean;
  /** Draws a picture from any address. Without it only a picture stored here
   *  is drawn, and one from anywhere else becomes a link carrying its name, so
   *  reading never fetches from a site nobody chose. Only for text the app
   *  ships or its operator writes. */
  remoteImages?: boolean;
  /** Drops block spacing and names pictures rather than drawing them, so the
   *  body can sit in a clamped preview. */
  compact?: boolean;
  /** Renders links and mentions as plain text. Set it when the body itself
   *  sits inside a link, which cannot legally contain one. */
  disableLinks?: boolean;
  /** Makes checklist boxes tick: a click hands back the content with that
   *  item ticked or unticked. For text being edited. */
  onChange?: (content: string) => void;
  ref?: Ref<HTMLDivElement>;
}

export const Markdown = ({
  content,
  className,
  surface = "document",
  mentions = false,
  zoomImages = true,
  remoteImages = false,
  compact = false,
  disableLinks = false,
  onChange,
  ref,
}: MarkdownProps) => {
  if (!content) {
    return null;
  }
  const preset: Surface = SURFACES[surface];

  // Mentions resolve before images, so an image-derived link is never
  // mistaken for one.
  const remarkPlugins: NonNullable<Options["remarkPlugins"]> = [remarkGfm];
  if (mentions) remarkPlugins.push(remarkMentions);
  if (!remoteImages) {
    remarkPlugins.push(
      preset.picture ? [remarkImageLinks, { keep: isStoredUpload }] : remarkImageLinks
    );
  }
  if (preset.lineBreaks) remarkPlugins.push(remarkLineBreaks);

  const components: Options["components"] = {
    a: disableLinks ? PlainAnchor : MarkdownAnchor,
    img: compact || !preset.picture ? ImageName : preset.picture,
    ...(mentions ? { span: disableLinks ? PlainMentionSpan : LinkedMentionSpan } : {}),
    ...(preset.paragraph && !compact ? { p: preset.paragraph } : {}),
    ...(onChange ? { li: ListItem, input: TaskBox } : {}),
  };
  // A checklist item's box is the first `[` after its list marker.
  const toggleTask =
    onChange &&
    ((itemStart: number) => {
      const box = content.indexOf("[", itemStart) + 1;
      if (box === 0) return;
      onChange(content.slice(0, box) + (content[box] === " " ? "x" : " ") + content.slice(box + 1));
    });

  const rendered = (
    <div ref={ref} className={cn(BASE_CLASS, preset.prose, !compact && preset.spacing, className)}>
      <TaskToggleContext.Provider value={toggleTask ?? null}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={preset.headingIds ? HEADING_ID_PLUGINS : undefined}
          components={components}
        >
          {content}
        </ReactMarkdown>
      </TaskToggleContext.Provider>
    </div>
  );
  // A body that sits inside a link leaves the click to it.
  if (!zoomImages || disableLinks || !preset.picture) return rendered;
  return <ImageLightboxScope>{rendered}</ImageLightboxScope>;
};

import {
  SiAirtable,
  SiFigma,
  SiGoogledocs,
  SiLoom,
  SiMiro,
  SiReddit,
  SiVimeo,
  SiX,
  SiYoutube,
} from "@icons-pack/react-simple-icons";
import { FileText, Link as LinkIcon } from "lucide-react";
import type { ComponentType } from "react";

export type SmartLinkProviderId =
  | "youtube"
  | "figma"
  | "loom"
  | "vimeo"
  | "google_docs"
  | "miro"
  | "airtable"
  | "microsoft_office"
  | "x"
  | "reddit"
  | "generic";

type IconComponent = ComponentType<{ className?: string; size?: number }>;

export interface SmartLinkProviderMatch {
  id: SmartLinkProviderId;
  label: string;
  canEmbed: boolean;
  embedSrc: string | null;
  icon: IconComponent;
  iframeAttrs: {
    allow?: string;
    referrerPolicy?: React.HTMLAttributeReferrerPolicy;
  };
  /** The thing's id on its own site, which an editor embed stores: a YouTube video's or an X post's. */
  ref?: string;
  /** Reads the height a framed post reports in a message, for pages that report one. */
  heightOf?: (data: unknown) => number | null;
  /**
   * i18n key (in the `files` namespace) for provider-specific
   * instructions shown when we recognize the provider but the URL isn't
   * an embed URL — e.g., a OneDrive *share* link vs a OneDrive *embed*
   * link. Rendered in the create dialog and on the viewer's link card.
   * Typed as a literal union so i18next's strict key check is satisfied.
   */
  embedHintKey?:
    | "smartLink.oneDriveEmbedHint"
    | "smartLink.sharePointEmbedHint"
    | "smartLink.airtableEmbedHint";
}

const GENERIC: SmartLinkProviderMatch = {
  id: "generic",
  label: "Link",
  canEmbed: false,
  embedSrc: null,
  icon: LinkIcon,
  iframeAttrs: {},
};

// youtu.be/<id>, youtube.com/watch?v=<id>, youtube.com/shorts/<id>,
// youtube.com/embed/<id>, youtube.com/playlist?list=<id>
function parseYouTubeId(url: URL): { kind: "video" | "playlist"; value: string } | null {
  // A video's id is eleven letters, digits, `-` or `_`.
  const video = (id: string | undefined) =>
    id && /^[\w-]{11}$/.test(id) ? { kind: "video" as const, value: id } : null;
  if (url.hostname === "youtu.be") {
    return video(url.pathname.slice(1).split("/")[0]);
  }
  if (!/(^|\.)youtube\.com$/.test(url.hostname)) return null;
  const v = url.searchParams.get("v");
  if (v) return video(v);
  const list = url.searchParams.get("list");
  if (url.pathname === "/playlist" && list) return { kind: "playlist", value: list };
  const shorts = /^\/shorts\/([^/?#]+)/.exec(url.pathname);
  if (shorts) return video(shorts[1]);
  const embed = /^\/embed\/([^/?#]+)/.exec(url.pathname);
  if (embed) return video(embed[1]);
  return null;
}

/** X's post frame reports its height as `twttr.private.resize`. */
function xPostHeight(data: unknown): number | null {
  const call = (data as { "twttr.embed"?: { method?: unknown; params?: unknown } } | null)?.[
    "twttr.embed"
  ];
  if (call?.method !== "twttr.private.resize" || !Array.isArray(call.params)) return null;
  const height = (call.params[0] as { height?: unknown } | undefined)?.height;
  return typeof height === "number" ? height : null;
}

/** Reddit's post frame reports its height as a `resize.embed` message, in JSON. */
function redditPostHeight(data: unknown): number | null {
  if (typeof data !== "string") return null;
  try {
    const message = JSON.parse(data) as { type?: unknown; data?: unknown };
    const height = Number(message.data);
    return message.type === "resize.embed" && Number.isFinite(height) ? height : null;
  } catch {
    return null;
  }
}

const PROVIDERS: Array<{
  id: SmartLinkProviderId;
  match: (url: URL) => SmartLinkProviderMatch | null;
}> = [
  {
    id: "youtube",
    match: (url) => {
      const id = parseYouTubeId(url);
      if (!id) return null;
      return {
        id: "youtube",
        label: "YouTube",
        canEmbed: true,
        icon: SiYoutube,
        embedSrc:
          id.kind === "video"
            ? `https://www.youtube-nocookie.com/embed/${id.value}`
            : `https://www.youtube-nocookie.com/embed/videoseries?list=${id.value}`,
        ref: id.kind === "video" ? id.value : undefined,
        iframeAttrs: {
          allow:
            "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture",
          referrerPolicy: "strict-origin-when-cross-origin",
        },
      };
    },
  },
  {
    id: "figma",
    match: (url) => {
      if (!/(^|\.)figma\.com$/.test(url.hostname)) return null;
      if (!/^\/(file|design|proto|board|slides)\//.test(url.pathname)) return null;
      return {
        id: "figma",
        label: "Figma",
        canEmbed: true,
        icon: SiFigma,
        embedSrc: `https://www.figma.com/embed?embed_host=initiative&url=${encodeURIComponent(
          url.toString()
        )}`,
        iframeAttrs: { allow: "fullscreen", referrerPolicy: "no-referrer" },
      };
    },
  },
  {
    id: "loom",
    match: (url) => {
      if (!/(^|\.)loom\.com$/.test(url.hostname)) return null;
      const m = /^\/share\/([a-f0-9]{24,})/.exec(url.pathname);
      if (!m) return null;
      return {
        id: "loom",
        label: "Loom",
        canEmbed: true,
        icon: SiLoom,
        embedSrc: `https://www.loom.com/embed/${m[1]}`,
        iframeAttrs: { allow: "fullscreen", referrerPolicy: "no-referrer" },
      };
    },
  },
  {
    id: "vimeo",
    match: (url) => {
      if (!/(^|\.)vimeo\.com$/.test(url.hostname)) return null;
      const m = /^\/(\d+)/.exec(url.pathname);
      if (!m) return null;
      return {
        id: "vimeo",
        label: "Vimeo",
        canEmbed: true,
        icon: SiVimeo,
        embedSrc: `https://player.vimeo.com/video/${m[1]}`,
        iframeAttrs: {
          allow: "autoplay; fullscreen; picture-in-picture",
          referrerPolicy: "strict-origin-when-cross-origin",
        },
      };
    },
  },
  {
    id: "google_docs",
    match: (url) => {
      if (url.hostname !== "docs.google.com") return null;
      const m = /^\/(document|spreadsheets|presentation|drawings)\/d\/([^/]+)/.exec(url.pathname);
      if (!m) return null;
      const [, kind, id] = m;
      return {
        id: "google_docs",
        label: "Google Docs",
        canEmbed: true,
        icon: SiGoogledocs,
        embedSrc: `https://docs.google.com/${kind}/d/${id}/preview`,
        iframeAttrs: { allow: "fullscreen", referrerPolicy: "no-referrer" },
      };
    },
  },
  {
    id: "miro",
    match: (url) => {
      if (!/(^|\.)miro\.com$/.test(url.hostname)) return null;
      // miro.com/app/board/<id>=/ or miro.com/app/live-embed/<id>/
      const m = /^\/app\/(?:board|live-embed)\/([^/?=]+)=?/.exec(url.pathname);
      if (!m) return null;
      return {
        id: "miro",
        label: "Miro",
        canEmbed: true,
        icon: SiMiro,
        embedSrc: `https://miro.com/app/live-embed/${m[1]}=/?embedAutoplay=true`,
        iframeAttrs: {
          allow: "fullscreen; clipboard-read; clipboard-write",
          referrerPolicy: "no-referrer",
        },
      };
    },
  },
  {
    id: "airtable",
    match: (url) => {
      if (!/(^|\.)airtable\.com$/.test(url.hostname)) return null;
      // Extract the share id and reconstruct a canonical embed URL so that
      // any user-appended query params (tracking junk, stale session args,
      // etc.) don't leak into the iframe src. Matches the YouTube/Loom/
      // Vimeo/Google Docs/Miro pattern of build-from-extracted-id.
      const m = /^\/embed\/([^/?#]+)/.exec(url.pathname);
      if (m) {
        return {
          id: "airtable",
          label: "Airtable",
          canEmbed: true,
          icon: SiAirtable,
          embedSrc: `https://airtable.com/embed/${m[1]}`,
          iframeAttrs: { referrerPolicy: "no-referrer" },
        };
      }
      // Recognized-but-not-embed: show the user how to get the embed URL.
      return {
        id: "airtable",
        label: "Airtable",
        canEmbed: false,
        embedSrc: null,
        icon: SiAirtable,
        iframeAttrs: {},
        embedHintKey: "smartLink.airtableEmbedHint",
      };
    },
  },
  {
    id: "microsoft_office",
    match: (url) => {
      // Office embeds are fragile: Microsoft's Office Online viewer
      // (view.officeapps.live.com/op/embed.aspx) requires a *direct* file URL,
      // not a share-page URL. We recognize URLs the user has explicitly
      // obtained from the provider's "Embed" feature:
      //
      //   • view.officeapps.live.com/op/embed.aspx?src=<direct file URL>
      //   • 1drv.ms/.../<id>?em=2                (OneDrive Embed shortlink)
      //   • onedrive.live.com/...?em=2           (OneDrive Embed long form)
      //   • onedrive.live.com/embed?resid=...    (older OneDrive Embed format)
      //   • <tenant>.sharepoint.com/...?action=embedview  (SharePoint Embed)
      //
      // `em=2` is OneDrive's telltale embed query param. Raw share URLs fall
      // through to the generic link card so the user can still save + click
      // out to them — better UX than silently rendering Microsoft's "File
      // not found" error inside an iframe.
      const isOfficeOnlineViewer = url.hostname === "view.officeapps.live.com";
      const isOneDriveHost =
        url.hostname === "1drv.ms" || /(^|\.)onedrive\.live\.com$/.test(url.hostname);
      const isSharePointHost = /\.sharepoint\.com$/.test(url.hostname);
      const isOneDriveEmbed =
        isOneDriveHost && (url.searchParams.get("em") === "2" || url.pathname === "/embed");
      const isSharePointEmbed = isSharePointHost && url.searchParams.get("action") === "embedview";

      if (isOfficeOnlineViewer || isOneDriveEmbed || isSharePointEmbed) {
        return {
          id: "microsoft_office",
          label: "Office",
          canEmbed: true,
          icon: FileText,
          embedSrc: url.toString(),
          iframeAttrs: { referrerPolicy: "no-referrer" },
        };
      }

      // Recognized host but not an embed URL — show instructions on how
      // to get the embed URL instead of silently falling through to a
      // generic link card.
      if (isOneDriveHost) {
        return {
          id: "microsoft_office",
          label: "OneDrive",
          canEmbed: false,
          embedSrc: null,
          icon: FileText,
          iframeAttrs: {},
          embedHintKey: "smartLink.oneDriveEmbedHint",
        };
      }
      if (isSharePointHost) {
        return {
          id: "microsoft_office",
          label: "SharePoint",
          canEmbed: false,
          embedSrc: null,
          icon: FileText,
          iframeAttrs: {},
          embedHintKey: "smartLink.sharePointEmbedHint",
        };
      }
      return null;
    },
  },
  {
    id: "x",
    match: (url) => {
      if (!/(^|\.)(x|twitter)\.com$/.test(url.hostname)) return null;
      // x.com/<handle>/status/<id>, x.com/i/web/status/<id>, twitter.com/…
      const m = /^\/(?:i\/web|[^/]+)\/status(?:es)?\/(\d+)/.exec(url.pathname);
      if (!m) return null;
      return {
        id: "x",
        label: "X",
        canEmbed: true,
        icon: SiX,
        embedSrc: `https://platform.twitter.com/embed/Tweet.html?id=${m[1]}&dnt=true`,
        ref: m[1],
        iframeAttrs: { referrerPolicy: "strict-origin-when-cross-origin" },
        heightOf: xPostHeight,
      };
    },
  },
  {
    id: "reddit",
    match: (url) => {
      if (!/(^|\.)reddit\.com$/.test(url.hostname)) return null;
      // reddit.com/r/<subreddit>/comments/<id>/<slug>/
      const m = /^\/r\/(\w+)\/comments\/([a-z0-9]+)(?:\/([\w%-]+))?/.exec(url.pathname);
      if (!m) return null;
      const [, subreddit, id, slug] = m;
      return {
        id: "reddit",
        label: "Reddit",
        canEmbed: true,
        icon: SiReddit,
        embedSrc: `https://embed.reddit.com/r/${subreddit}/comments/${id}/${slug ? `${slug}/` : ""}`,
        iframeAttrs: { referrerPolicy: "strict-origin-when-cross-origin" },
        heightOf: redditPostHeight,
      };
    },
  },
];

/**
 * The set of embeddable providers, for UI affordances that advertise what
 * smart-links can render (e.g. an icon row under the URL input). Order
 * controls display order.
 */
export interface SupportedProviderBadge {
  id: SmartLinkProviderId;
  label: string;
  icon: IconComponent;
}

export const SUPPORTED_PROVIDER_BADGES: readonly SupportedProviderBadge[] = [
  { id: "youtube", label: "YouTube", icon: SiYoutube },
  { id: "figma", label: "Figma", icon: SiFigma },
  { id: "loom", label: "Loom", icon: SiLoom },
  { id: "vimeo", label: "Vimeo", icon: SiVimeo },
  { id: "google_docs", label: "Google Docs", icon: SiGoogledocs },
  { id: "miro", label: "Miro", icon: SiMiro },
  { id: "airtable", label: "Airtable", icon: SiAirtable },
  { id: "microsoft_office", label: "Office", icon: FileText },
  { id: "x", label: "X", icon: SiX },
  { id: "reddit", label: "Reddit", icon: SiReddit },
];

export function matchSmartLinkProvider(url: string): SmartLinkProviderMatch {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return GENERIC;
    for (const p of PROVIDERS) {
      const hit = p.match(parsed);
      if (hit) return hit;
    }
  } catch {
    /* invalid URL — fall through */
  }
  return GENERIC;
}

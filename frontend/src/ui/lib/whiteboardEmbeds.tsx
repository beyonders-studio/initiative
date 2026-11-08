import { EmbedFrame } from "@/ui/embed-frame";
import { matchSmartLinkProvider, type SmartLinkProviderMatch } from "@/ui/lib/smartLinkProviders";

/** Sites a whiteboard draws with the app's own post frame rather than Excalidraw's. */
const POST_HOSTS = ["twitter.com", "x.com", "reddit.com"];

/** The app's match for a link on a post site, or undefined for any other link. */
function postEmbed(link: string): SmartLinkProviderMatch | undefined {
  let url: URL;
  try {
    url = new URL(/^[a-z][a-z\d+.-]*:/i.test(link) ? link : `https://${link}`);
  } catch {
    return undefined;
  }
  const host = url.hostname;
  if (!POST_HOSTS.some((site) => host === site || host.endsWith(`.${site}`))) return undefined;
  return matchSmartLinkProvider(url.toString());
}

/** Excalidraw's `validateEmbeddable`: a post site's link embeds when the app can frame it. */
export function validateEmbeddable(link: string): boolean | undefined {
  const embed = postEmbed(link);
  return embed === undefined ? undefined : embed.embedSrc !== null;
}

/** Excalidraw's `renderEmbeddable`: a post site's link fills its box with the app's frame. */
export function renderEmbeddable(element: { link: string | null }) {
  const embed = element.link ? postEmbed(element.link) : undefined;
  if (!embed?.embedSrc) return null;
  return (
    <EmbedFrame
      src={embed.embedSrc}
      title={embed.label}
      {...embed.iframeAttrs}
      className="h-full w-full border-0"
    />
  );
}

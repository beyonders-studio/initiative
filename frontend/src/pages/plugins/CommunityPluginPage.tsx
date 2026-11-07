/**
 * A plug-in's own surface, in an iframe.
 *
 * The security shape, which mirrors what the mint endpoint already enforces:
 *
 * 1. The server decides whether a surface may be opened — the install must be
 *    enabled, its registration live, and the seat's placement and roles must
 *    admit the caller. A refusal never reaches the plug-in.
 * 2. The token is delivered by `postMessage` to the iframe's own origin, never
 *    in the URL, so it stays out of history, referrers and proxy logs.
 * 3. Inbound messages are ignored unless `event.origin` is one the registration
 *    listed and `event.source` is the frame this page mounted.
 * 4. The token is one-shot, so a reloading page asks again and gets a fresh
 *    one rather than being stuck until the page is reloaded.
 * 5. The frame is granted the browser features the surface's manifest declared,
 *    and no others.
 *
 * The handoff also carries `sells`: whether this host may lead anyone to a
 * purchase here (a billing portal is configured, and this device may sell —
 * see `@/lib/storeSelling`). A plug-in's page hides its own purchase copy when
 * it is false.
 */

import { Loader2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginHandoff } from "@/api/generated/initiativeAPI.schemas";
import {
  createCommunityPluginHandoff,
  createInitiativePluginHandoff,
} from "@/api/generated/plugins/plugins";
import { ReportButton } from "@/components/moderation/ReportButton";
import { PluginProviderNotice, pluginNoticeKey } from "@/components/plugins/PluginProviderNotice";
import {
  EditorSkeleton,
  SkeletonPillRow,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { effectiveThemeColors } from "@/hooks/useColorTheme";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import { useServer } from "@/hooks/useServer";
import { useTheme } from "@/hooks/useTheme";
import { showsCuratedCatalogueOnly } from "@/lib/marketplaceCuration";
import { pageAllow, pluginPages } from "@/lib/pluginSurfaces";
import { getItem, setItem } from "@/lib/storage";
import { DEFAULT_THEME } from "@/lib/themes";
import { cn } from "@/lib/utils";
import { localized } from "@/lib/widgets/widgetMeta";

/** The message names a page and this host agree on. */
const READY = "initiative-plugin:ready";
const HANDOFF = "initiative-plugin:handoff";
const ERROR = "initiative-plugin:error";
const LOCALE = "initiative-plugin:locale";
const THEME = "initiative-plugin:theme";

export interface CommunityPluginPageProps {
  pluginId: number;
  /**
   * The initiative this page is being read inside, if any. It selects the
   * surfaces on offer, and it travels to the plug-in in the minted token — so the
   * plug-in can scope what it shows without asking a second question.
   */
  initiativeId?: number;
}

export function CommunityPluginPage({ pluginId, initiativeId }: CommunityPluginPageProps) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const communityId = useActiveCommunityId();
  const { activeCommunity } = useCommunities();
  const detail = useCommunityPluginDetail(pluginId);
  const plugin = detail.data;

  // Only the surfaces the server says this reader opens here.
  const pages = useMemo(() => pluginPages(plugin, initiativeId), [plugin, initiativeId]);
  const [surfaceId, setSurfaceId] = useState<string | null>(null);
  const active = pages.find((page) => page.id === surfaceId) ?? pages[0] ?? null;
  // The surface as a plain id, so a refetch that hands back an equal-but-new
  // definition does not read as a surface change and mint a token nobody asked
  // for.
  const activeId = active?.id ?? null;

  const { user } = useAuth();

  // The iPhone app says who a plug-in comes from before it first opens one
  // that BeyondersStudio does not publish, and opens nothing until the member
  // continues.
  const { getServerOrigin } = useServer();
  const noticeKey = pluginNoticeKey(getServerOrigin() ?? "", user?.id ?? 0, communityId, pluginId);
  const [, noteAcknowledged] = useState(0);
  const held =
    Boolean(plugin) &&
    showsCuratedCatalogueOnly() &&
    !plugin?.listing?.first_party &&
    getItem(noticeKey) !== "1";
  const acknowledge = () => {
    void setItem(noticeKey, "1");
    noteAcknowledged((count) => count + 1);
  };

  const [handoff, setHandoff] = useState<CommunityPluginHandoff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // Whether the token we hold has already been handed over. A later `ready`
  // means the page reloaded itself and the old token is spent, so the next
  // one is minted fresh.
  const spentRef = useRef(false);

  // Two routes, because where a surface was opened is the route's to say: the
  // initiative in the token is the one whose gate this request passed, not a
  // value the page hands over.
  const mint = useCallback(
    () =>
      (initiativeId === undefined
        ? createCommunityPluginHandoff(communityId, pluginId, activeId ?? "")
        : createInitiativePluginHandoff(
            communityId,
            initiativeId,
            pluginId,
            activeId ?? ""
          )) as unknown as Promise<CommunityPluginHandoff>,
    [communityId, initiativeId, pluginId, activeId]
  );

  // A plug-in the deployment's term has no seat free for is not opened: the
  // page shows the request in its place, and mints nothing.
  const termFull = plugin?.entitlement?.reason === "term_full";

  // Mint for the surface being opened. Re-runs when the surface changes, which
  // is also when the iframe is replaced.
  useEffect(() => {
    if (!activeId || held || termFull) return;
    let cancelled = false;
    setHandoff(null);
    setError(null);
    spentRef.current = false;
    void mint()
      .then((fresh) => {
        if (!cancelled) setHandoff(fresh);
      })
      .catch(() => {
        if (!cancelled) setError(t("plugins:page.handoffFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, held, termFull, mint, t]);

  // A plug-in's page has an origin of its own: one shared with the app or the
  // server is not framed.
  const origin = useMemo(() => {
    if (!handoff?.page_url) return null;
    try {
      const page = new URL(handoff.page_url).origin;
      return page === window.location.origin || page === getServerOrigin() ? null : page;
    } catch {
      return null;
    }
  }, [handoff?.page_url, getServerOrigin]);

  const allowed = useMemo(
    () => new Set(handoff?.allowed_origins ?? []),
    [handoff?.allowed_origins]
  );

  // The reader's appearance travels with the token so the page opens already
  // wearing it: the resolved mode ("system" is resolved on this side — the
  // plug-in should follow this page, not re-derive the OS preference), and the
  // effective palette, since an iframe on another origin cannot read this
  // document's custom properties.
  const { resolvedTheme } = useTheme();
  const colorThemeId = user?.color_theme ?? DEFAULT_THEME;
  const themeColors = useMemo(
    () => effectiveThemeColors(colorThemeId, resolvedTheme),
    [colorThemeId, resolvedTheme]
  );

  // Hold the translator in a ref so a language change cannot re-attach the
  // listener mid-exchange. Same for the theme.
  const tRef = useRef(t);
  tRef.current = t;
  const localeRef = useRef(i18n.language);
  localeRef.current = i18n.language;
  const themeRef = useRef(resolvedTheme);
  themeRef.current = resolvedTheme;
  const themeColorsRef = useRef(themeColors);
  themeColorsRef.current = themeColors;
  // Asked at delivery rather than read at render: a phone's store may not
  // have answered yet when the frame announces itself.
  const { billing, openPortal, sellsNow } = useBillingPortal();
  const sellsNowRef = useRef(sellsNow);
  sellsNowRef.current = sellsNow;

  useEffect(() => {
    if (!origin || !handoff) return;

    // A token names one surface, and switching tabs replaces the iframe. So a
    // re-mint still in flight when that happens must not deliver: its token is
    // for the surface that was open when it was asked for, and the frame now
    // waiting shows a different one. Same plug-in, same origin, so the origin check
    // cannot tell them apart.
    let cancelled = false;

    const send = async (target: Window, token: CommunityPluginHandoff) => {
      const sells = await sellsNowRef.current();
      // Dropped if the surface changed, or the frame was replaced, meanwhile.
      if (cancelled || iframeRef.current?.contentWindow !== target) return;
      target.postMessage(
        {
          type: HANDOFF,
          handoff_token: token.handoff_token,
          expires_in_seconds: token.expires_in_seconds,
          audience: token.audience,
          surface_id: token.surface_id,
          locale: localeRef.current,
          theme: themeRef.current,
          theme_colors: themeColorsRef.current,
          sells,
        },
        // Never "*": that would hand the token to whatever happens to be
        // loaded in the frame.
        origin
      );
    };

    const onMessage = (event: MessageEvent) => {
      if (!allowed.has(event.origin)) return;
      // This page exchanges with one window: the frame it mounted. An
      // announcement is matched to it by window rather than by origin, since
      // a plug-in may hold more than one window at the same address.
      const target = iframeRef.current?.contentWindow;
      if (!target || event.source !== target) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === READY) {
        const failed = () => {
          if (!cancelled) setError(tRef.current("plugins:page.handoffFailed"));
        };
        if (!spentRef.current) {
          spentRef.current = true;
          send(target, handoff).catch(failed);
          return;
        }
        void mint()
          .then((fresh) => {
            // Dropped if the surface changed while this was in flight, or if
            // the frame that asked is no longer the mounted one.
            if (cancelled || iframeRef.current?.contentWindow !== target) return;
            return send(target, fresh);
          })
          .catch(() => {
            if (!cancelled) setError(tRef.current("plugins:page.handoffFailed"));
          });
      } else if (data.type === ERROR) {
        setError(
          typeof data.message === "string" ? data.message : tRef.current("plugins:page.failed")
        );
      }
    };

    window.addEventListener("message", onMessage);
    return () => {
      cancelled = true;
      window.removeEventListener("message", onMessage);
    };
  }, [origin, allowed, handoff, mint]);

  // Keep the page in step with a language change.
  useEffect(() => {
    if (!origin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage({ type: LOCALE, locale: i18n.language }, origin);
  }, [origin, i18n.language]);

  // And with an appearance change — flipping light/dark (or the color theme)
  // recolors the page in place.
  useEffect(() => {
    if (!origin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage({ type: THEME, theme: resolvedTheme, colors: themeColors }, origin);
  }, [origin, resolvedTheme, themeColors]);

  if (detail.isLoading) {
    return (
      <SkeletonRegion className="space-y-4">
        <SkeletonPillRow count={3} pillClassName="h-8 w-24" />
        <EditorSkeleton className="min-h-[60vh]" />
      </SkeletonRegion>
    );
  }

  if (!plugin) return <Notice title={t("plugins:page.notFound")} />;
  if (!plugin.enabled) return <Notice title={t("plugins:page.disabled", { name: plugin.name })} />;
  if (!plugin.available)
    return (
      <Notice
        title={t("plugins:page.unavailable", { name: plugin.name })}
        description={t("plugins:page.unavailableDescription")}
      />
    );
  // The deployment's term has no seat free for this community: in place of
  // the plug-in, the request that would bring it back, which the seat makes
  // in the billing portal.
  if (termFull) {
    const listingUid = plugin.listing_uid;
    return (
      <Notice
        title={t("plugins:install.termFull", { name: plugin.name })}
        description={
          activeCommunity?.can.seat && billing && listingUid
            ? undefined
            : t("plugins:install.termFullAskAdmins")
        }
        action={
          activeCommunity?.can.seat && billing && listingUid ? (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              onClick={() =>
                void openPortal(activeCommunity.id, "manage", null, {
                  request: "plugin",
                  listing: listingUid,
                })
              }
            >
              {t("plugins:install.termFullRequest")}
            </Button>
          ) : undefined
        }
      />
    );
  }
  // Anything but our own can be reported from here, on every platform.
  const reportable = plugin.listing?.first_party ? null : plugin.listing;
  const report = reportable ? (
    <ReportButton targetType="marketplace_listing" targetId={reportable.id} />
  ) : null;

  if (!active)
    return <Notice title={t("plugins:page.noSurface", { name: plugin.name })} action={report} />;
  if (held)
    return (
      <PluginProviderNotice name={plugin.name} listing={plugin.listing} onContinue={acknowledge} />
    );
  if (error) return <Notice title={t("plugins:page.failed")} description={error} />;
  if (handoff?.page_url && !origin) return <Notice title={t("plugins:page.failed")} />;

  return (
    <div className="flex h-full flex-col">
      {(pages.length > 1 || reportable) && (
        <div className="flex shrink-0 items-center gap-1 border-b px-2">
          {pages.length > 1 &&
            pages.map((page) => (
              <button
                key={page.id}
                type="button"
                onClick={() => setSurfaceId(page.id)}
                className={cn(
                  "border-b-2 px-3 py-2 text-sm",
                  page.id === active.id
                    ? "border-primary font-medium"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {localized(page.name, i18n.language) || page.id}
              </button>
            ))}
          {reportable && (
            <ReportButton
              targetType="marketplace_listing"
              targetId={reportable.id}
              className="ml-auto h-8 w-8"
            />
          )}
        </div>
      )}
      {handoff && origin ? (
        <iframe
          // Keyed by surface so switching tabs mounts a fresh frame rather
          // than reusing one that already spent its token.
          key={active.id}
          ref={iframeRef}
          src={handoff.page_url}
          title={plugin.name}
          className="block min-h-0 w-full flex-1 border-0 bg-background"
          // Notably absent: allow-top-navigation, allow-modals,
          // allow-popups-to-escape-sandbox.
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
          referrerPolicy="no-referrer"
          // Built from what this surface's manifest declared; empty when it
          // declared none.
          allow={pageAllow(active)}
        />
      ) : (
        <div className="flex flex-1 items-center gap-2 p-4 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("plugins:page.connecting")}
        </div>
      )}
    </div>
  );
}

function Notice({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1">
          <CardTitle>{title}</CardTitle>
          {action}
        </div>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
    </Card>
  );
}

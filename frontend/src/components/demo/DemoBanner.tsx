import { Link } from "@tanstack/react-router";
import { Hourglass, Presentation } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useLeaveDemoLead, usePublishDemoPitch, useReadDemoPitch } from "@/api/generated/demo/demo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useCommunities } from "@/hooks/useCommunities";
import { type DemoCopy, useDemoCopy, useIsDemoServer } from "@/hooks/useDemoCopy";
import { useLiveClockValue, useRelativeTime } from "@/hooks/useRelativeTime";
import { getErrorMessage } from "@/lib/errorMessage";
import { listFormat, numberFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";

/** Publishing is queued, so the pitch is read again this often until the new
 *  version lands, and given up on after this long. */
const PUBLISH_POLL_MS = 2_000;
const PUBLISH_TIMEOUT_MS = 120_000;

/** Whole hours and minutes until `expiresAt`, as "3h 12m" in `locale`, never
 *  below none. */
const timeLeft = (expiresAt: number, now: number, locale: string): string => {
  const left = Math.max(0, Math.ceil((expiresAt - now) / 60_000));
  const whole = Math.floor(left / 60);
  const unit = (value: number, unit: "hour" | "minute") =>
    numberFormat(locale, { style: "unit", unit, unitDisplay: "narrow" }).format(value);
  const rest = unit(left % 60, "minute");
  return whole > 0
    ? listFormat(locale, { type: "unit", style: "narrow" }).format([unit(whole, "hour"), rest])
    : rest;
};

/** The row both banners share: an icon, what it says, and what can be done. */
const BannerRow = ({
  icon,
  message,
  children,
}: {
  icon: ReactNode;
  message: ReactNode;
  children: ReactNode;
}) => (
  <div className="flex min-h-12 items-center gap-3 border-b px-4 py-2 text-sm md:border-b-0">
    {icon}
    <p className="min-w-0 flex-1">{message}</p>
    <div className="flex shrink-0 items-center gap-3">{children}</div>
  </div>
);

/** "Leave your email": a small form that leaves an address for a follow-up. */
const LeadPopover = () => {
  const { t } = useTranslation("auth");
  const emailId = useId();
  const [email, setEmail] = useState("");
  const lead = useLeaveDemoLead();

  return (
    <Popover>
      <PopoverTrigger className="text-primary underline-offset-4 hover:underline">
        {t("demo.lead.action")}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        {lead.isSuccess ? (
          <p role="status">{t("demo.lead.thanks")}</p>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              lead.mutate({ data: { email: email.trim() } });
            }}
          >
            <p className="font-medium">{t("demo.lead.title")}</p>
            <p className="text-muted-foreground text-sm">{t("demo.lead.pitch")}</p>
            <div className="space-y-2">
              <Label htmlFor={emailId}>{t("demo.lead.label")}</Label>
              <Input
                id={emailId}
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            {lead.isError ? (
              <p className="text-destructive text-sm" role="alert">
                {getErrorMessage(lead.error, "auth:demo.lead.failed")}
              </p>
            ) : null}
            <Button type="submit" className="w-full" disabled={lead.isPending}>
              {t("demo.lead.send")}
            </Button>
          </form>
        )}
      </PopoverContent>
    </Popover>
  );
};

/**
 * A demo visitor's copy, and how long it has left, in the row the recents tabs
 * use for everyone else.
 */
export const DemoBanner = ({ copy }: { copy: DemoCopy }) => {
  const { t, i18n } = useTranslation("auth");
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const expiresAt = new Date(copy.expiresAt).getTime();
  const remaining = useLiveClockValue((now) => timeLeft(expiresAt, now, locale));

  return (
    <BannerRow
      icon={<Hourglass className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />}
      message={t("demo.banner.message", { community: copy.community?.name ?? "", remaining })}
    >
      <LeadPopover />
      <Link to="/welcome" className="text-primary underline-offset-4 hover:underline">
        {t("demo.banner.mainSite")}
      </Link>
    </BannerRow>
  );
};

/**
 * A pitch's admins see which version visitors get, and publish the one they
 * have now. `onPublished` is handed the publish time the press was made
 * against, so the pitch can be read until it moves.
 */
const PitchBanner = ({
  communityId,
  lastPublishedAt,
  onPublished,
}: {
  communityId: number;
  lastPublishedAt: string | null;
  onPublished: (before: string | null) => void;
}) => {
  const { t } = useTranslation("auth");
  const when = useRelativeTime(lastPublishedAt);
  const publish = usePublishDemoPitch({
    mutation: {
      onSuccess: () => toast.success(t("demo.pitch.published")),
      onError: (error) => toast.error(getErrorMessage(error, "auth:demo.pitch.failed")),
    },
  });

  return (
    <BannerRow
      icon={<Presentation className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />}
      message={when ? t("demo.pitch.message", { when }) : t("demo.pitch.unpublished")}
    >
      <Button
        size="sm"
        disabled={publish.isPending}
        onClick={() =>
          publish.mutate({ communityId }, { onSuccess: () => onPublished(lastPublishedAt) })
        }
      >
        {t("demo.pitch.publish")}
      </Button>
    </BannerRow>
  );
};

/**
 * The first row of the app's top bar: a demo visitor's banner, a pitch's
 * Publish banner for its admins on the demo server, or `children` (the recents
 * tabs) for everyone else.
 */
export const DemoBannerOrTabs = ({ children }: { children: ReactNode }) => {
  const copy = useDemoCopy();
  const { activeCommunity } = useCommunities();
  const administers = !copy && activeCommunity?.can.administer === true;
  const demo = useIsDemoServer(administers);
  const communityId = activeCommunity?.id ?? 0;
  // A publish still on its way: the community and the publish time it was
  // pressed against.
  const [publishing, setPublishing] = useState<{
    communityId: number;
    before: string | null;
  } | null>(null);
  const unmoved = (publishedAt: string | null | undefined) =>
    publishing?.communityId === communityId && (publishedAt ?? null) === publishing.before;
  const pitch = useReadDemoPitch(communityId, {
    query: {
      enabled: administers && demo,
      staleTime: 60_000,
      refetchInterval: (query) =>
        unmoved(query.state.data?.last_published_at) ? PUBLISH_POLL_MS : false,
    },
  });
  const waiting = unmoved(pitch.data?.last_published_at);

  useEffect(() => {
    if (!waiting) return;
    const timer = window.setTimeout(() => setPublishing(null), PUBLISH_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [waiting]);

  if (copy) return <DemoBanner copy={copy} />;
  if (administers && pitch.data?.is_pitch) {
    return (
      <PitchBanner
        communityId={communityId}
        lastPublishedAt={pitch.data.last_published_at ?? null}
        onPublished={(before) => setPublishing({ communityId, before })}
      />
    );
  }
  return children;
};

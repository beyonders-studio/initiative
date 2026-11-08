import { useRouter, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { communityPath, isCommunityScopedPath } from "@/lib/communityUrl";
import { normalizeLegacyTarget } from "@/lib/entityResolver";
import { Button } from "@/ui/button";

const normalizeTarget = (raw: string): string => {
  const decoded = decodeURIComponent(raw);
  if (!decoded) {
    return "/";
  }
  const path = decoded.startsWith("/") ? decoded : `/${decoded}`;
  // Smart links minted before tools were addressed inside their initiative are
  // still arriving from stored notification rows; map them onto the resolver.
  return normalizeLegacyTarget(path);
};

export const NavigatePage = () => {
  const { t } = useTranslation("nav");
  const { user, loading: authLoading } = useAuth();
  const { communities, activeCommunityId, switchCommunity } = useCommunities();
  const searchParams = useSearch({ strict: false }) as { community_id?: string; target?: string };
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(true);

  const communityParam = searchParams.community_id;
  const targetParam = searchParams.target;

  const destination = useMemo(() => {
    if (!targetParam) {
      return null;
    }
    try {
      return normalizeTarget(targetParam);
    } catch {
      return null;
    }
  }, [targetParam]);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    if (!user) {
      setError(t("navigate.signInRequired"));
      setIsProcessing(false);
      return;
    }
    if (!communityParam || !destination) {
      setError(t("navigate.missingDestination"));
      setIsProcessing(false);
      return;
    }
    let parsedCommunityId = Number(communityParam);
    if (!Number.isFinite(parsedCommunityId)) {
      parsedCommunityId = Number.parseInt(communityParam, 10);
    }
    if (!Number.isFinite(parsedCommunityId)) {
      setError(t("navigate.invalidCommunityId"));
      setIsProcessing(false);
      return;
    }

    // Check if user has access to this community
    const hasAccess = communities.some((g) => g.id === parsedCommunityId);
    if (!hasAccess) {
      setError(t("navigate.noAccess"));
      setIsProcessing(false);
      return;
    }

    setError(null);
    setIsProcessing(true);

    // Redirect to new community-scoped URL format if the target isn't already community-scoped
    const finalDestination = isCommunityScopedPath(destination)
      ? destination
      : communityPath(parsedCommunityId, destination);

    const performNavigation = async () => {
      try {
        // Sync community context in background (but URL already has community info)
        if (activeCommunityId !== parsedCommunityId) {
          await switchCommunity(parsedCommunityId);
        }
        // A query (an event's `?occurrence=`) stays search rather than path.
        router.navigate(
          finalDestination.includes("?")
            ? { href: finalDestination, replace: true }
            : { to: finalDestination, replace: true }
        );
      } catch (err) {
        console.error("Failed to follow smart link", err);
        setError(t("navigate.switchError"));
        setIsProcessing(false);
      }
    };
    void performNavigation();
  }, [
    authLoading,
    user,
    communities,
    communityParam,
    activeCommunityId,
    switchCommunity,
    router,
    destination,
    t,
  ]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="font-medium text-base text-destructive">{error}</p>
        <Button onClick={() => router.navigate({ to: "/", replace: true })}>
          {t("navigate.goHome")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-muted-foreground text-sm">
        {isProcessing ? t("navigate.redirecting") : t("navigate.finalizing")}
      </p>
    </div>
  );
};

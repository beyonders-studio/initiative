import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { LoginProviderEntry } from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useCommunityLoginProviders } from "@/hooks/useCommunityAuthPolicy";
import { useServer } from "@/hooks/useServer";
import { providerSignInHref } from "@/lib/returnPath";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { SkeletonRegion } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";

/**
 * A community's sign-in page — the URL its admins share with members.
 *
 * The community authenticates nobody. These are the deployment's own
 * providers, filtered to the ones this community counts as its own, and each
 * button leads to the deployment's sign-in. What the community made of that
 * sign-in — whether the arrival counts as theirs, and whether it joins them —
 * is applied when they reach the community, not here.
 *
 * Unauthenticated by design; a signed-in visitor just adds the provider to
 * their session (step-up union).
 */
export const CommunityLoginPage = () => {
  const { t } = useTranslation(["auth", "common"]);
  const params = useParams({ strict: false }) as { communityId?: string };
  const communityId = params.communityId ? Number(params.communityId) : 0;
  const { isNativePlatform } = useServer();

  const providersQuery = useCommunityLoginProviders(communityId, {
    enabled: communityId > 0 && !isNativePlatform,
  });
  const providers = providersQuery.data?.providers ?? [];
  const communityName = providersQuery.data?.community_name ?? null;

  const signIn = (entry: LoginProviderEntry) => {
    window.location.href = providerSignInHref(entry.login_url, `/c/${communityId}`);
  };

  return (
    <SignInFrame>
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="items-center text-center">
          <CardTitle>{communityName ?? t("communityLogin.title")}</CardTitle>
          <CardDescription>{t("communityLogin.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {isNativePlatform ? (
            <p className="text-center text-muted-foreground text-sm">
              {t("communityLogin.nativeUnsupported")}
            </p>
          ) : providersQuery.isLoading ? (
            <SkeletonRegion>
              <Skeleton className="h-10 w-full" />
            </SkeletonRegion>
          ) : providers.length === 0 ? (
            <p className="text-center text-muted-foreground text-sm">
              {t("communityLogin.noProviders")}
            </p>
          ) : (
            providers.map((provider) => (
              <Button
                key={provider.slug}
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => signIn(provider)}
              >
                <ProviderMark icon={provider.icon} className="h-4 w-4" />
                {t("login.continueWith", { provider: provider.display_name })}
              </Button>
            ))
          )}
        </CardContent>
        <CardFooter className="justify-center">
          <Link className="text-primary text-sm underline-offset-4 hover:underline" to="/login">
            {t("communityLogin.otherSignIn")}
          </Link>
        </CardFooter>
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};

import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { acceptInvite, useGetInviteStatus } from "@/api/generated/communities/communities";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { formatDateTime } from "@/ui/lib/formatDate";
import { SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";

export const InvitePage = () => {
  const { code = "" } = useParams({ strict: false }) as { code: string };
  const normalizedCode = code.trim();
  const { user, refreshUser } = useAuth();
  const { refreshCommunities } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const inviteQuery = useGetInviteStatus(encodeURIComponent(normalizedCode), {
    // One code's status is never a placeholder for another's: the card and the
    // accept button describe the code in the URL.
    query: { enabled: Boolean(normalizedCode), placeholderData: undefined },
  });
  const status = inviteQuery.data ?? null;
  const loading = Boolean(normalizedCode) && inviteQuery.isPending;
  const error = !normalizedCode
    ? t("invite.codeMissing")
    : inviteQuery.isError
      ? t("invite.unableToLoad")
      : status && !status.is_valid
        ? (status.reason ?? t("invite.noLongerValid"))
        : null;
  const accept = useApiMutation(
    { mutationFn: acceptInvite },
    {
      // Refresh both explicitly: joining changes the user's community list, and the
      // switcher only reloads when asked to. (It deliberately does not key off
      // the user object's identity — refreshUser() always returns a fresh one,
      // which would refetch every community on any profile change.)
      onSuccess: () => Promise.all([refreshUser(), refreshCommunities()]),
    }
  );

  const inviteValid = Boolean(status?.is_valid);
  const inviteTitle = inviteValid
    ? t("invite.title", { communityName: status?.community_name ?? t("invite.thisCommunity") })
    : t("invite.titleDefault");

  return (
    <SignInFrame>
      <Card className="w-full max-w-lg shadow-lg">
        <CardHeader>
          <CardTitle>{inviteTitle}</CardTitle>
          <CardDescription>
            {loading
              ? t("invite.checking")
              : inviteValid
                ? t("invite.acceptDescription")
                : (error ?? t("invite.couldNotValidate"))}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <SkeletonRegion>
              <SkeletonLines lines={3} />
            </SkeletonRegion>
          ) : (
            <>
              <div className="rounded border bg-muted/40 p-4 text-sm">
                <p>
                  <span className="font-medium">{t("invite.inviteCodeLabel")}</span>{" "}
                  {normalizedCode || "—"}
                </p>
                <p>
                  <span className="font-medium">{t("invite.communityLabel")}</span>{" "}
                  {status?.community_name ?? t("invite.unknown")}
                </p>
                {status?.expires_at ? (
                  <p>
                    <span className="font-medium">{t("invite.expiresLabel")}</span>{" "}
                    {formatDateTime(status.expires_at)}
                  </p>
                ) : null}
                {status?.max_uses ? (
                  <p>
                    <span className="font-medium">{t("invite.usesLabel")}</span> {status.uses ?? 0}{" "}
                    / {status.max_uses}
                  </p>
                ) : null}
              </div>
              {inviteValid ? (
                <div className="space-y-2 text-muted-foreground text-sm">
                  <p>{t("invite.alreadyHaveAccount")}</p>
                  <p>
                    {t("invite.needAccount")}{" "}
                    <Link
                      className="text-primary underline-offset-4 hover:underline"
                      to="/start"
                      search={normalizedCode ? { invite_code: normalizedCode } : {}}
                    >
                      {t("invite.registerWithInvite")}
                    </Link>
                    .
                  </p>
                </div>
              ) : null}
              {accept.error ? (
                <p className="text-destructive text-sm">
                  {getErrorMessage(accept.error, "communities:invite.unableToAccept")}
                </p>
              ) : null}
              {accept.isSuccess ? (
                <p className="text-primary text-sm">{t("invite.accepted")}</p>
              ) : null}
              <div className="flex flex-col gap-2">
                {accept.isSuccess ? (
                  <Button asChild className="w-full">
                    <Link to="/">{t("invite.continueToApp")}</Link>
                  </Button>
                ) : (
                  <Button
                    onClick={() => accept.mutate({ code: normalizedCode })}
                    disabled={!user || !inviteValid || accept.isPending}
                    className="w-full"
                  >
                    {accept.isPending ? t("invite.accepting") : t("invite.acceptInvite")}
                  </Button>
                )}

                {!user ? (
                  <Link
                    className="text-center text-primary text-sm underline-offset-4 hover:underline"
                    to="/login"
                    search={normalizedCode ? { invite_code: normalizedCode } : undefined}
                  >
                    {t("invite.signInToAccept")}
                  </Link>
                ) : null}
              </div>
            </>
          )}
        </CardContent>
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};

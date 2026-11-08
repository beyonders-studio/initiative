/**
 * Who has knocked on this initiative, and what the manager does about it.
 *
 * It sits in the members tab because that is what it is: the same act as adding
 * someone to the roster by hand, only asked for first. Approving writes the
 * ordinary membership row every join path ends at, so the person appears in the
 * table above it; denying leaves nothing behind but the history — and a denied
 * requester may ask again, which is why a repeat is marked rather than hidden.
 *
 * The list itself is manager-only on the server; this renders only where the
 * roster is managed, so the two agree.
 */

import { Check, Clock, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { InitiativeJoinRequestRead } from "@/api/generated/initiativeAPI.schemas";
import { JoinRequestStatus } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useInitiativeJoinRequests, useResolveJoinRequest } from "@/hooks/useInitiatives";
import { toast } from "@/lib/mascotToast";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { RelativeTime } from "@/ui/relative-time";

export interface InitiativeJoinRequestQueueProps {
  initiativeId: number;
}

export const InitiativeJoinRequestQueue = ({ initiativeId }: InitiativeJoinRequestQueueProps) => {
  const { t } = useTranslation("initiatives");

  const queueQuery = useInitiativeJoinRequests(initiativeId);
  const requests = queueQuery.data ?? [];

  const resolveRequest = useResolveJoinRequest({
    onSuccess: (request) => {
      const name = getUserDisplayName(request.user, t("joinRequests.unknownRequester"));
      toast.success(
        request.status === JoinRequestStatus.approved
          ? t("joinRequests.approved", { name })
          : t("joinRequests.denied", { name })
      );
    },
  });
  const resolvingId = resolveRequest.isPending ? resolveRequest.variables?.requestId : undefined;

  // An empty queue is the normal state of a healthy door — it earns a line, not
  // a card of its own, and never appears while the first read is in flight.
  if (queueQuery.isPending || (requests.length === 0 && !queueQuery.isError)) {
    return null;
  }

  const renderRequest = (request: InitiativeJoinRequestRead) => {
    const displayName = getUserDisplayName(request.user, t("joinRequests.unknownRequester"));
    const avatarSrc = getAvatarSrc(request.user);
    const isResolving = resolvingId === request.id;

    return (
      <li key={request.id} className="flex flex-col gap-3 border-b p-4 last:border-b-0 sm:p-4">
        <div className="flex min-w-0 items-start gap-3">
          <Avatar className="h-8 w-8 shrink-0">
            {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
            {/* `null` for an anonymized account, so the deterministic colour
                doesn't outlive the identity it was derived from. */}
            <AvatarFallback
              userId={isAnonymizedUser(request.user) ? null : request.user.id}
              className="text-xs"
            >
              {getInitialsForUser(request.user)}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium text-sm">{displayName}</span>
              <RelativeTime
                date={request.created_at}
                className="shrink-0 text-muted-foreground text-xs"
              />
              {/* Design §13: a denied requester may ask again, so the manager
                  reading this row is told they have answered it before. */}
              {request.prior_denials > 0 ? (
                <Badge variant="outline" className="gap-1 font-normal text-xs">
                  <Clock className="h-3 w-3" aria-hidden="true" />
                  {t("joinRequests.priorDenials", { count: request.prior_denials })}
                </Badge>
              ) : null}
            </div>
            {request.message ? (
              <p className="wrap-break-word whitespace-pre-wrap text-muted-foreground text-sm">
                {request.message}
              </p>
            ) : (
              <p className="text-muted-foreground text-sm italic">{t("joinRequests.noMessage")}</p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={resolveRequest.isPending}
            onClick={() =>
              resolveRequest.mutate({ initiativeId, requestId: request.id, approved: false })
            }
          >
            <X className="h-4 w-4" />
            {t("joinRequests.deny")}
          </Button>
          <Button
            size="sm"
            disabled={resolveRequest.isPending}
            pending={isResolving}
            onClick={() =>
              resolveRequest.mutate({ initiativeId, requestId: request.id, approved: true })
            }
          >
            <Check className="h-4 w-4" />
            {t("joinRequests.approve")}
          </Button>
        </div>
      </li>
    );
  };

  return (
    <SettingsSection
      title={
        <span className="flex flex-wrap items-center gap-2">
          {t("joinRequests.queueTitle")}
          {requests.length > 0 ? <Badge variant="secondary">{requests.length}</Badge> : null}
        </span>
      }
      description={t("joinRequests.queueDescription")}
      contentClassName="p-0"
    >
      {queueQuery.isError ? (
        <p className="p-4 text-destructive text-sm">{t("joinRequests.queueLoadError")}</p>
      ) : (
        <ul className="divide-y">{requests.map(renderRequest)}</ul>
      )}
    </SettingsSection>
  );
};

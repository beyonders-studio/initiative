/**
 * Who has knocked on an initiative or a community, and what its managers do
 * about it.
 *
 * It sits beside the roster because that is what it is: the same act as adding
 * someone to the roster by hand, only asked for first. Approving writes the
 * ordinary membership row every join path ends at, so the person appears in the
 * table beside it; denying leaves nothing behind but the history — and a denied
 * requester may ask again, which is why a repeat is marked rather than hidden,
 * where the page knows of one.
 *
 * Each page reads its own queue and answers it with its own hooks; this draws
 * the rows. The list itself is managers-only on the server, and each page
 * renders this only where the roster is managed, so the two agree.
 */

import { Check, Clock, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import {
  type AvatarSourceUser,
  type DisplayableUser,
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { RelativeTime } from "@/ui/relative-time";
import { StatusMessage } from "@/ui/status-message";

export interface JoinRequestRow {
  id: number;
  user: DisplayableUser & AvatarSourceUser & { id: number };
  message: string | null;
  created_at: string;
  /** How often this requester was turned down before, where the page knows. */
  prior_denials?: number;
}

export interface JoinRequestQueueProps {
  description: string;
  /** The page's read of its queue. */
  queue: { data?: JoinRequestRow[]; isPending: boolean; isError: boolean; refetch: () => unknown };
  /** The request being answered, while one is. */
  answeringId: number | undefined;
  onAnswer: (request: JoinRequestRow, approved: boolean) => void;
}

export const JoinRequestQueue = ({
  description,
  queue,
  answeringId,
  onAnswer,
}: JoinRequestQueueProps) => {
  const { t } = useTranslation("common");
  const requests = queue.data ?? [];
  const answering = answeringId !== undefined;

  // An empty queue is the normal state of a healthy door — it earns a line, not
  // a card of its own, and never appears while the first read is in flight.
  if (queue.isPending || (requests.length === 0 && !queue.isError)) {
    return null;
  }

  const renderRequest = (request: JoinRequestRow) => {
    const displayName = getUserDisplayName(request.user, t("joinRequests.unknownRequester"));
    const avatarSrc = getAvatarSrc(request.user);

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
              {/* A denied requester may ask again, so the manager reading this
                  row is told they have answered it before. */}
              {request.prior_denials ? (
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
            disabled={answering}
            onClick={() => onAnswer(request, false)}
          >
            <X className="h-4 w-4" />
            {t("joinRequests.deny")}
          </Button>
          <Button
            size="sm"
            disabled={answering}
            pending={answeringId === request.id}
            onClick={() => onAnswer(request, true)}
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
      description={description}
      contentClassName="p-0"
    >
      {queue.isError ? (
        <StatusMessage onRetry={queue.refetch} />
      ) : (
        <ul className="divide-y">{requests.map(renderRequest)}</ul>
      )}
    </SettingsSection>
  );
};

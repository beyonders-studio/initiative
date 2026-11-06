import { Link } from "@tanstack/react-router";
import { MessageSquare, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DirectMessagePermissionRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  useAcceptConnection,
  useConnections,
  useDmPermission,
  useMessageRequests,
  useRequestConnection,
  useRequestMessage,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/mascotToast";
import { getUrlHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface ConnectionActionButtonsProps {
  /** The account being acted on. A connection is addressed by handle, so both
   *  halves of it are needed rather than only the id. */
  user: { id: number; username: string; discriminator: number };
  className?: string;
  /**
   * The server's answer about this person, where the surface already has it.
   * A list asks once for its whole page; without this each row would ask for
   * itself, which is a request per row.
   */
  permission?: DirectMessagePermissionRead | null;
}

/**
 * The two things somebody usually came to a profile to do, as buttons.
 *
 * The menu beside these holds everything a person can do about another; these
 * are the one or two worth a click rather than a click and a read. Which one
 * shows follows the same `dm_permission` the menu reads: `open` opens the
 * conversation, `may_request` asks for one, and `denied` offers neither.
 *
 * A request already sent stays on screen as a disabled button rather than
 * disappearing: the gap where it was would read as the ask having failed.
 */
export const ConnectionActionButtons = ({
  user,
  className,
  permission: supplied,
}: ConnectionActionButtonsProps) => {
  const { t } = useTranslation(["connections", "settings"]);

  // Only where the caller has not already been told.
  const own = useDmPermission(supplied === undefined ? user.id : undefined);
  const permission = supplied ?? own.data;
  const { data: connections } = useConnections();
  const { data: messageRequests } = useMessageRequests();

  const acceptConnection = useAcceptConnection();
  const requestConnection = useRequestConnection();
  const requestMessage = useRequestMessage();

  const isConnection = (connections?.accepted ?? []).some((g) => g.user_id === user.id);
  // Which way a pending request points decides what there is to do about it.
  // Rolled together, an ask *they* sent reads back as one you sent -- a spent
  // button where the answer belongs.
  const theyAsked = (connections?.incoming ?? []).some((g) => g.user_id === user.id);
  const youAsked = (connections?.outgoing ?? []).some((g) => g.user_id === user.id);
  const messagePending = (messageRequests?.outgoing ?? []).some((g) => g.user_id === user.id);

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {permission?.permission === "open" ? (
        <Button asChild size="sm">
          <Link to="/messages" search={{ with: getUrlHandle(user) }}>
            <MessageSquare className="size-4" aria-hidden />
            {t("actions.message")}
          </Link>
        </Button>
      ) : null}

      {permission?.permission === "may_request" ? (
        <Button
          size="sm"
          disabled={messagePending || requestMessage.isPending}
          onClick={() =>
            requestMessage.mutate(
              { data: { user_id: user.id } },
              { onSuccess: () => toast.success(t("actions.askSent")) }
            )
          }
        >
          <MessageSquare className="size-4" aria-hidden />
          {messagePending ? t("actions.asked") : t("actions.ask")}
        </Button>
      ) : null}

      {/* Connecting and messaging are separate rules, so the server is asked
          about both. Offering a request that would be refused is worse than
          offering nothing: it reads as a way in, and answers with an error. */}
      {isConnection ? null : theyAsked ? (
        <Button
          size="sm"
          variant="outline"
          disabled={acceptConnection.isPending}
          onClick={() => acceptConnection.mutate({ userId: user.id })}
        >
          <UserPlus className="size-4" aria-hidden />
          {t("actions.acceptConnection")}
        </Button>
      ) : !(permission?.may_connect ?? false) ? null : (
        <Button
          size="sm"
          variant="outline"
          disabled={youAsked || requestConnection.isPending}
          onClick={() =>
            requestConnection.mutate(
              { data: { username: user.username, discriminator: user.discriminator } },
              { onSuccess: () => toast.success(t("settings:privacy.connections.sent")) }
            )
          }
        >
          <UserPlus className="size-4" aria-hidden />
          {youAsked ? t("actions.connectPending") : t("actions.connect")}
        </Button>
      )}
    </div>
  );
};

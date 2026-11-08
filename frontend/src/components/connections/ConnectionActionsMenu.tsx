import { Link } from "@tanstack/react-router";
import { MoreHorizontal } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DirectMessagePermissionRead } from "@/api/generated/initiativeAPI.schemas";
import {
  useConnections,
  useDmPermission,
  useIgnoreAccount,
  useIgnoredAccounts,
  useRemoveConnection,
  useRequestConnection,
  useRequestMessage,
  useStopIgnoring,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/mascotToast";
import { getUrlHandle, getUserHandle } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

/**
 * The things this menu can offer that a surface might offer for itself.
 *
 * `profile` is here for the opposite reason to the rest: most surfaces that
 * draw this menu already *are* the person or link to them, so it is the one
 * that is usually left out rather than usually kept.
 */
type MenuAction = "profile" | "message" | "connect" | "ask";

interface ConnectionActionsMenuProps {
  /** The account being acted on. The handle is what a connection is addressed
   *  by, so both halves of it are needed, not just the id. */
  user: { id: number; username: string; discriminator: number };
  /** Rendered inside a link or a row that is itself clickable. */
  className?: string;
  /**
   * The server's answer about this person, where the surface already has it.
   * A list asks once for its whole page; without this each row would ask for
   * itself, which is a request per row.
   */
  permission?: DirectMessagePermissionRead | null;
  /**
   * What the menu must not offer, because the surface around it already does —
   * a row of buttons, a link on the name. Everything else
   * appears, subject to what the server says is possible, so a person is never
   * offered the same thing twice and never quietly missing an action either.
   */
  omit?: ReadonlyArray<MenuAction>;
  /** What the surface itself may do about this person, after the rest: a
   *  community's roster adds the changes to their membership. */
  children?: ReactNode;
}

/**
 * What one person can do about another, wherever they meet them.
 *
 * Until this existed the writes had no caller: ignoring was reachable only by
 * already knowing somebody's exact handle and opening Settings, which is the
 * opposite of the moment somebody reaches for it. So the menu goes where the
 * person is — their profile, a community's roster, a conversation in the
 * list, a row in the picker.
 *
 * It holds *everything* one account can do about another, and each surface
 * names only what it already offers beside it. That way the menu is the
 * complete answer to "what else can I do about them" by default, and the ones
 * that go missing go missing on purpose.
 *
 * Which items are possible is read from ``dm_permission``, one collapsed value
 * the server computes. *Ask to message* on ``may_request``, nothing on
 * ``denied`` — and because every refusal collapses into that one word, a menu
 * built from it says nothing about which refusal it is.
 */
export const ConnectionActionsMenu = ({
  user,
  className,
  omit = [],
  permission: supplied,
  children,
}: ConnectionActionsMenuProps) => {
  const { t } = useTranslation(["connections", "settings"]);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  const hidden = new Set(omit);
  const shows = (action: MenuAction) => !hidden.has(action);
  // Only where the caller has not already been told -- and only where the
  // answer is used at all: with every way in left to something else, nothing
  // below reads it, and a list of rows would each be asking for nothing.
  const wantsPermission = shows("message") || shows("connect") || shows("ask");
  const own = useDmPermission(supplied === undefined && wantsPermission ? user.id : undefined);
  const permission = supplied ?? own.data;
  const { data: connections } = useConnections();
  const { data: ignored } = useIgnoredAccounts();

  const requestConnection = useRequestConnection();
  const requestMessage = useRequestMessage();
  const removeConnection = useRemoveConnection();
  const ignore = useIgnoreAccount();
  const stopIgnoring = useStopIgnoring();

  const isConnection = (connections?.accepted ?? []).some((g) => g.user_id === user.id);
  const isPending = (connections?.incoming ?? [])
    .concat(connections?.outgoing ?? [])
    .some((g) => g.user_id === user.id);
  const isIgnored = (ignored?.items ?? []).some((row) => row.user_id === user.id);

  return (
    <>
      {/* `modal={false}`: this menu is drawn inside the mobile sidebar, which
          is a non-modal drawer, and a modal dropdown nested in one dismisses it
          on open — the same reason the initiative rows and the user footer set
          it. */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={className}
            aria-label={t("actions.label", { handle: user.username })}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {/* Where a row leads to a conversation rather than to the person, this
              is how the person is still one click away. */}
          {shows("profile") && (
            <DropdownMenuItem asChild>
              <Link to="/u/$handle" params={{ handle: getUrlHandle(user) }}>
                {t("actions.viewProfile")}
              </Link>
            </DropdownMenuItem>
          )}
          {/* The whole handle, number included -- the only form that addresses
              anybody. A bare name is refused by every field that takes one. */}
          <DropdownMenuItem
            onSelect={() => {
              void navigator.clipboard
                ?.writeText(getUserHandle(user))
                .then(() => toast.success(t("actions.handleCopied")));
            }}
          >
            {t("actions.copyHandle")}
          </DropdownMenuItem>
          {shows("message") && permission?.permission === "open" && (
            <DropdownMenuItem asChild>
              <Link to="/messages" search={{ with: getUrlHandle(user) }}>
                {t("actions.message")}
              </Link>
            </DropdownMenuItem>
          )}
          {/* Connecting is its own decision, separate from messaging: an
              account that takes no messages may still take a connection. A
              request the server would refuse is not worth offering. */}
          {shows("connect") && !isConnection && !isPending && permission?.may_connect && (
            <DropdownMenuItem
              onSelect={() =>
                requestConnection.mutate(
                  { data: { username: user.username, discriminator: user.discriminator } },
                  { onSuccess: () => toast.success(t("settings:privacy.connections.sent")) }
                )
              }
            >
              {t("actions.connect")}
            </DropdownMenuItem>
          )}
          {shows("ask") && permission?.permission === "may_request" && (
            <DropdownMenuItem
              onSelect={() =>
                requestMessage.mutate(
                  { data: { user_id: user.id } },
                  { onSuccess: () => toast.success(t("actions.askSent")) }
                )
              }
            >
              {t("actions.ask")}
            </DropdownMenuItem>
          )}
          {isConnection && (
            <DropdownMenuItem onSelect={() => setConfirmingRemove(true)}>
              {t("actions.removeConnection")}
            </DropdownMenuItem>
          )}
          {isIgnored ? (
            <DropdownMenuItem onSelect={() => stopIgnoring.mutate({ userId: user.id })}>
              {t("actions.stopIgnoring")}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem
              onSelect={() => ignore.mutate({ userId: user.id })}
              className="text-destructive"
            >
              {t("actions.ignore")}
            </DropdownMenuItem>
          )}
          {children ? (
            <>
              <DropdownMenuSeparator />
              {children}
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Removing a connection can take the open channel with it, and whether
          it does depends on the other account's own policy — which is theirs,
          not something to read off this dialog. So it says what is certain and
          does not guess which case this pair is. */}
      <ConfirmDialog
        open={confirmingRemove}
        onOpenChange={setConfirmingRemove}
        title={t("actions.removeConnectionTitle")}
        description={t("actions.removeConnectionBody")}
        confirmLabel={t("actions.removeConnection")}
        destructive
        isLoading={removeConnection.isPending}
        onConfirm={() =>
          removeConnection.mutate(
            { userId: user.id },
            { onSuccess: () => setConfirmingRemove(false) }
          )
        }
      />
    </>
  );
};

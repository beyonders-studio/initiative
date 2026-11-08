/**
 * Who reaches an outside system through this community, and the levers for it.
 *
 * Installing a plug-in is an admin decision, and so is who may use it. What an
 * admin gets here is governance, not inspection: which member connected as
 * which vendor account, when, and three ways to end it —
 *
 * - **Revoke** deletes that member's stored credential and tells the plug-in to let
 *   go at the vendor. They may connect again.
 * - **Block** does the same and refuses the next attempt, for "this person
 *   should no longer reach that system through us" without uninstalling the plug-in
 *   for everyone.
 * - **Revoke all** does it for every member at once, for a suspected plug-in or
 *   vendor compromise, leaving the install and its configuration standing.
 *
 * Beside them, each member's answers to the plug-in's requests to act as them,
 * which an admin can end and never give.
 *
 * Deliberately absent: the values. No admin workflow needs the bytes, and being
 * able to end someone's access is strictly more useful than being able to read
 * a token you could then use as them.
 */

import { ShieldOff, UserX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CommunityPluginConnectionSummary,
  type CommunityPluginMemberConnection,
  type CommunityPluginMemberConsent,
  ConsentAccess,
  ConsentStatus,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useBlockMemberConnection,
  useCommunityPluginMembers,
  useRevokeAllConnections,
  useRevokeAllConsents,
  useRevokeMemberConnection,
  useRevokeMemberConsents,
} from "@/hooks/useCommunityPluginDetail";
import { useUserSearch } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDate } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName } from "@/lib/userDisplay";
import { localized } from "@/lib/widgets/widgetMeta";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { PaginationBar } from "@/ui/pagination-bar";
import { Skeleton } from "@/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

export interface PluginMembersPanelProps {
  pluginId: number;
  /** Rendered only for community admins; the server refuses everyone else anyway. */
  enabled: boolean;
}

export function PluginMembersPanel({ pluginId, enabled }: PluginMembersPanelProps) {
  const { t } = useTranslation(["plugins", "common"]);
  const [page, setPage] = useState(1);
  const membersQuery = useCommunityPluginMembers(pluginId, page, enabled);
  const summary = membersQuery.data?.summary ?? [];
  const items = membersQuery.data?.items ?? [];
  const consents = membersQuery.data?.consents ?? [];
  // Names for the members on this page only, rather than the whole roster.
  const pageUserIds = [...new Set([...items, ...consents].map((row) => row.user_id))].sort(
    (a, b) => a - b
  );
  const usersQuery = useUserSearch({
    userIds: pageUserIds,
    pageSize: Math.max(pageUserIds.length, 1),
    enabled: enabled && pageUserIds.length > 0,
  });
  const revokeAll = useRevokeAllConnections(pluginId);
  const [confirmingRevokeAll, setConfirmingRevokeAll] = useState(false);

  if (!enabled) return null;
  if (membersQuery.isLoading) return <Skeleton className="h-24 w-full" />;

  const consentSummary = membersQuery.data?.consent_summary;
  const totalCount = membersQuery.data?.total_count ?? 0;
  const pageSize = membersQuery.data?.page_size ?? 1;
  // The server's page, which falls back to the first when this one emptied.
  const current = membersQuery.data?.page ?? page;

  if (!summary.length && !consentSummary?.member_count) {
    return <p className="text-muted-foreground text-sm">{t("plugins:members.noPersonal")}</p>;
  }

  const nameFor = (userId: number) =>
    getUserDisplayName(
      usersQuery.data?.items.find((user) => user.id === userId),
      t("plugins:members.unknownMember", { id: userId })
    );

  return (
    <div className="space-y-4">
      {summary.map((connection) => (
        <ConnectionMembers
          key={connection.connection_id}
          pluginId={pluginId}
          summary={connection}
          items={items.filter((item) => item.connection_id === connection.connection_id)}
          nameFor={nameFor}
        />
      ))}

      {/* The inbound direction, beside the outbound one: both answer "what does
          this plug-in have of this member's", so an admin governing one finds the
          other in the same place. */}
      {consentSummary && consentSummary.member_count > 0 && (
        <MemberConsents
          pluginId={pluginId}
          consents={consents}
          allowedCount={consentSummary.allowed_count}
          anyOpen={consentSummary.open_count > 0}
          nameFor={nameFor}
        />
      )}

      <PaginationBar
        page={current}
        pageSize={pageSize}
        totalCount={totalCount}
        hasNext={Boolean(membersQuery.data?.has_next)}
        onPageChange={setPage}
      />

      {summary.length > 0 && (
        <div>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setConfirmingRevokeAll(true)}
            pending={revokeAll.isPending}
          >
            {t("plugins:members.revokeAll")}
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirmingRevokeAll}
        onOpenChange={setConfirmingRevokeAll}
        title={t("plugins:members.revokeAllTitle")}
        description={t("plugins:members.revokeAllBody")}
        confirmLabel={t("plugins:members.revokeAll")}
        isLoading={revokeAll.isPending}
        destructive
        onConfirm={() =>
          revokeAll.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("plugins:members.revokedAll"));
              setConfirmingRevokeAll(false);
            },
            onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
          })
        }
      />
    </div>
  );
}

/** Whether an answer still stands or still waits: the ones an admin can end. */
const isOpen = (consent: CommunityPluginMemberConsent) =>
  consent.status === ConsentStatus.granted || consent.status === ConsentStatus.pending;

function consentStatusKey(consent: CommunityPluginMemberConsent) {
  switch (consent.status) {
    case ConsentStatus.granted:
      return consent.granted_access === ConsentAccess.read_write
        ? "plugins:consent.statusReadWrite"
        : "plugins:consent.statusRead";
    case ConsentStatus.declined:
      return "plugins:consent.statusDeclined";
    case ConsentStatus.revoked:
      return "plugins:consent.statusRevoked";
    default:
      return "plugins:consent.statusPending";
  }
}

/**
 * What each member answered when the plug-in asked to act as them, one row per
 * member with every request they were asked.
 *
 * An admin ends answers and cannot give one: both buttons here revoke. Whose
 * name the plug-in may carry is answered by that person, so an admin who takes it
 * away has taken it away — they have not moved it to a setting they control.
 */
function MemberConsents({
  pluginId,
  consents,
  allowedCount,
  anyOpen,
  nameFor,
}: {
  pluginId: number;
  /** The answers of the members on this page. */
  consents: CommunityPluginMemberConsent[];
  /** Across every member, not just this page. */
  allowedCount: number;
  anyOpen: boolean;
  nameFor: (userId: number) => string;
}) {
  const { t } = useTranslation(["plugins", "common"]);
  const revoke = useRevokeMemberConsents(pluginId);
  const revokeAll = useRevokeAllConsents(pluginId);
  const [confirming, setConfirming] = useState(false);

  const byMember = new Map<number, CommunityPluginMemberConsent[]>();
  for (const consent of consents) {
    byMember.set(consent.user_id, [...(byMember.get(consent.user_id) ?? []), consent]);
  }

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium text-sm">{t("plugins:consent.membersTitle")}</h3>
        <span className="text-muted-foreground text-xs">
          {t("plugins:consent.allowedCount", { count: allowedCount })}
        </span>
      </header>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("plugins:members.member")}</TableHead>
              <TableHead>{t("plugins:consent.requestsColumn")}</TableHead>
              <TableHead className="text-right">{t("common:actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...byMember.entries()].map(([userId, rows]) => (
              <TableRow key={userId}>
                <TableCell className="align-top font-medium">{nameFor(userId)}</TableCell>
                <TableCell>
                  <ul className="space-y-1">
                    {rows.map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="break-words">
                          {row.purpose == null ? t("plugins:consent.pluginWide") : row.label}
                        </span>
                        <Badge
                          variant={row.status === ConsentStatus.granted ? "secondary" : "outline"}
                        >
                          {t(consentStatusKey(row))}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </TableCell>
                <TableCell className="text-right align-top">
                  {rows.some(isOpen) && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoke.isPending}
                      onClick={() =>
                        revoke.mutate(userId, {
                          onSuccess: () => toast.success(t("plugins:consent.memberRevoked")),
                          onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
                        })
                      }
                    >
                      <UserX className="h-3.5 w-3.5" aria-hidden />
                      {t("plugins:members.revoke")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {anyOpen && (
        <Button
          size="sm"
          variant="destructive"
          pending={revokeAll.isPending}
          onClick={() => setConfirming(true)}
        >
          {t("plugins:consent.revokeAll")}
        </Button>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("plugins:consent.revokeAllTitle")}
        description={t("plugins:consent.revokeAllBody")}
        confirmLabel={t("plugins:consent.revokeAll")}
        isLoading={revokeAll.isPending}
        destructive
        onConfirm={() =>
          revokeAll.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("plugins:consent.revokedAll"));
              setConfirming(false);
            },
            onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
          })
        }
      />
    </section>
  );
}

function ConnectionMembers({
  pluginId,
  summary,
  items,
  nameFor,
}: {
  pluginId: number;
  summary: CommunityPluginConnectionSummary;
  items: CommunityPluginMemberConnection[];
  nameFor: (userId: number) => string;
}) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const revoke = useRevokeMemberConnection(pluginId);
  const block = useBlockMemberConnection(pluginId);

  const name = localized(summary.label, i18n.language) ?? summary.connection_id;

  // Takes the translated message rather than a key, so every call site spells
  // its key as a literal and a missing one is a type error there instead of a
  // raw key surfacing in a toast.
  const notify = (message: string) => ({
    onSuccess: () => toast.success(message),
    onError: (error: unknown) => toast.error(getErrorMessage(error, "plugins:error")),
  });

  const revokeMember = (item: CommunityPluginMemberConnection) =>
    revoke.mutate(
      { userId: item.user_id, connectionId: item.connection_id },
      notify(t("plugins:members.revoked"))
    );

  const toggleBlock = (item: CommunityPluginMemberConnection) =>
    block.mutate(
      { userId: item.user_id, connectionId: item.connection_id, blocked: item.blocked },
      notify(t(item.blocked ? "plugins:members.unblocked" : "plugins:members.blockedDone"))
    );

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium text-sm">{name}</h3>
        {/* The aggregate an admin actually wants, before the rows. */}
        <span className="text-muted-foreground text-xs">
          {t("plugins:members.connectedCount", {
            connected: summary.connected_count,
            total: summary.member_count,
          })}
        </span>
        {summary.blocked_count > 0 && (
          <Badge variant="outline">
            {t("plugins:members.blockedCount", { count: summary.blocked_count })}
          </Badge>
        )}
      </header>

      {items.length ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("plugins:members.member")}</TableHead>
                <TableHead>{t("plugins:members.account")}</TableHead>
                <TableHead>{t("plugins:members.since")}</TableHead>
                <TableHead className="text-right">{t("common:actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={`${item.connection_id}-${item.user_id}`}>
                  <TableCell className="font-medium">{nameFor(item.user_id)}</TableCell>
                  <TableCell>
                    {item.blocked ? (
                      <Badge variant="destructive">{t("plugins:members.blocked")}</Badge>
                    ) : (
                      (item.account_label ??
                      t(`plugins:connections.status.${item.status}`, {
                        defaultValue: item.status,
                      }))
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {formatDate(item.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      {!item.blocked && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revoke.isPending}
                          onClick={() => revokeMember(item)}
                        >
                          <UserX className="h-3.5 w-3.5" aria-hidden />
                          {t("plugins:members.revoke")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant={item.blocked ? "outline" : "destructive"}
                        disabled={block.isPending}
                        onClick={() => toggleBlock(item)}
                      >
                        <ShieldOff className="h-3.5 w-3.5" aria-hidden />
                        {item.blocked ? t("plugins:members.unblock") : t("plugins:members.block")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{t("plugins:members.nobodyYet")}</p>
      )}
    </section>
  );
}

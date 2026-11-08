/**
 * Who may reach this account, and who it has agreed something with.
 *
 * Three lists that move together — accepting a connection opens a channel,
 * leaving a community closes one — so every mutation here invalidates all of
 * them, the same set the `connections` realtime frame invalidates. A tab that
 * acted and a tab that only watched end up saying the same thing.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  readDmPermissions,
  useAcceptConnection as useAcceptConnectionMutation,
  useAcceptMessageRequest as useAcceptMessageRequestMutation,
  useIgnoreAccountByHandle as useIgnoreAccountByHandleMutation,
  useIgnoreAccount as useIgnoreAccountMutation,
  useListConnections,
  useListIgnoredAccounts,
  useListMessageRequests,
  useReadDmSettings,
  useRemoveConnection as useRemoveConnectionMutation,
  useRemoveMessageRequest as useRemoveMessageRequestMutation,
  useRequestConnection as useRequestConnectionMutation,
  useRequestMessage as useRequestMessageMutation,
  useStopIgnoringAccount,
  useUpdateDmSettings as useUpdateDmSettingsMutation,
} from "@/api/generated/direct-messages/direct-messages";
import type {
  DirectMessagePermissionRead,
  DirectMessagePermissionsResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useAppConfig } from "@/hooks/useAppConfig";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/** Everything a change to one of these lists can affect. */
export const refreshConnectionLists = () => {
  void invalidate(q.contactGrants(), q.ignoredAccounts(), q.dmSettings());
};

/**
 * What every one of these mutations does on the way out.
 *
 * `onSettled` refreshes all three lists; `onError` says so out loud. These are
 * ordinary conflicts rather than bugs — accepting a request that was withdrawn
 * a moment ago, removing a connection somebody else already removed — and the
 * lists refresh either way, so without a word the row simply changes under the
 * reader with nothing to explain it. There is no global mutation error handler
 * to fall back on, so it lives here rather than at each call site.
 */
const reportAndRefresh = {
  mutation: {
    onSettled: refreshConnectionLists,
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "errors:CONTACT_GRANT_CANNOT_REACH")),
  },
};

/**
 * The same, minus the toast: the connect-by-handle field reports next to the
 * input, where the mistake usually is.
 */
const refreshOnly = { mutation: { onSettled: refreshConnectionLists } };

/**
 * Whether this deployment offers direct messages at all.
 *
 * Every read below is gated on it, so a deployment with messaging switched off
 * asks none of these questions rather than asking and being refused. True until
 * the boot config arrives, and true if it never does: messaging is what most
 * deployments have, and a config that failed to load is not an instruction to
 * take it away.
 */
export const useDirectMessagesEnabled = (): boolean => useAppConfig().directMessagesEnabled;

// ── Reads ───────────────────────────────────────────────────────────────────

export const useDmSettings = () =>
  useReadDmSettings({
    query: { enabled: useDirectMessagesEnabled() },
  });

/**
 * What the reader may do about one account: ``open``, ``may_request`` or
 * ``denied``.
 *
 * One value with nothing beside it — the server collapses every refusal into
 * ``denied`` on purpose, so a menu built from this cannot tell the reasons
 * apart either.
 */
export const useDmPermission = (userId: number | undefined) => {
  const dmEnabled = useDirectMessagesEnabled();
  return useQuery({
    // Keyed like the bulk read's page of one, so whatever makes those stale
    // reaches this too.
    queryKey: ["dm", "permissions", [userId]],
    queryFn: () => readDmPermissions({ user_ids: [userId as number] }),
    // Your own account is left out of the answer: every action on it is refused.
    select: (data): DirectMessagePermissionRead =>
      data.permissions[String(userId)] ?? { permission: "denied", may_connect: false },
    enabled: dmEnabled && typeof userId === "number",
  });
};
/** The most accounts one question may name, which the server enforces. */
const PERMISSION_LIMIT = 100;

/**
 * One object out of however many questions it took to answer for everybody.
 *
 * All of them or none: half an answer set is indistinguishable from a complete
 * one at the call site, and the two surfaces reading it disagree about what a
 * missing entry means -- the actions menu leaves an item out, the picker lets
 * the row be clicked. Publishing a partial map would make that disagreement
 * outlive the loading it belongs to. Absent, both behave the way they do
 * before any answer has arrived, which is what is true.
 */
const mergePermissions = (
  results: { data?: DirectMessagePermissionsResponse; isPending: boolean }[]
) => ({
  data:
    results.length > 0 && results.every((result) => result.data)
      ? {
          permissions: Object.assign(
            {},
            ...results.map((result) => result.data?.permissions ?? {})
          ) as DirectMessagePermissionsResponse["permissions"],
        }
      : undefined,
  isPending: results.some((result) => result.isPending),
});

/**
 * The same two answers, for a page of people at once.
 *
 * A surface listing members draws a control per row, and asking per row is a
 * request per row -- up to a hundred when a roster page is full. One question
 * about many subjects instead, cached under the ids it was asked about.
 *
 * A POST that reads: the subjects are a list rather than an address, so
 * `useQuery` rather than a mutation, with the ids in the key.
 *
 * Past the server's limit it asks again rather than answering for fewer people
 * than it was given. A caller that dropped the remainder would leave a control
 * built on a missing answer -- which reads as a refusal on one surface and as
 * consent on another -- so nobody handed to this goes unanswered.
 */
export const useDmPermissions = (userIds: number[]) => {
  const dmEnabled = useDirectMessagesEnabled();
  const batches = useMemo(() => {
    const ids = [...new Set(userIds)].sort((a, b) => a - b);
    const out: number[][] = [];
    for (let at = 0; at < ids.length; at += PERMISSION_LIMIT) {
      out.push(ids.slice(at, at + PERMISSION_LIMIT));
    }
    return out;
  }, [userIds]);

  return useQueries({
    queries: batches.map((ids) => ({
      queryKey: ["dm", "permissions", ids],
      queryFn: () => readDmPermissions({ user_ids: ids }),
      enabled: dmEnabled,
    })),
    combine: mergePermissions,
  });
};

export const useConnections = () =>
  useListConnections({
    query: { enabled: useDirectMessagesEnabled() },
  });
export const useMessageRequests = () =>
  useListMessageRequests({
    query: { enabled: useDirectMessagesEnabled() },
  });
export const useIgnoredAccounts = () =>
  // Paged, so the options are the second argument: the whole list, gated.
  useListIgnoredAccounts(undefined, {
    query: { enabled: useDirectMessagesEnabled() },
  });

// ── Writes ──────────────────────────────────────────────────────────────────

export const useUpdateDmSettings = () => useUpdateDmSettingsMutation(reportAndRefresh);

export const useRequestConnection = () => useRequestConnectionMutation(refreshOnly);
export const useAcceptConnection = () => useAcceptConnectionMutation(reportAndRefresh);
export const useRemoveConnection = () => useRemoveConnectionMutation(reportAndRefresh);

export const useRequestMessage = () => useRequestMessageMutation(reportAndRefresh);
export const useAcceptMessageRequest = () => useAcceptMessageRequestMutation(reportAndRefresh);
export const useRemoveMessageRequest = () => useRemoveMessageRequestMutation(reportAndRefresh);

export const useIgnoreAccount = () => useIgnoreAccountMutation(reportAndRefresh);
export const useIgnoreAccountByHandle = () => useIgnoreAccountByHandleMutation(refreshOnly);
export const useStopIgnoring = () => useStopIgnoringAccount(reportAndRefresh);

/**
 * A handle typed as `name#1234`, split for the connection and ignore endpoints.
 *
 * A connection is addressed by handle whatever the target's policy: it is the
 * only shape that reaches an account on Private, which is never offered from a
 * roster or a picker.
 */
export const parseHandle = (raw: string): { username: string; discriminator: number } | null => {
  const match = /^@?([^#\s]{1,32})#(\d{1,4})$/.exec(raw.trim());
  if (!match) return null;
  return { username: match[1], discriminator: Number(match[2]) };
};

/**
 * How many people are waiting on an answer from this account.
 *
 * Both kinds, because both are answered in the same place: the requests
 * section of My Messages takes a connection request and a message request
 * alike, so a mark that counted only one of them would send somebody to a
 * screen with more on it than the mark admitted. Only incoming — an ask you
 * sent is waiting on them, not on you.
 */
export const usePendingConnectionRequests = (): number => {
  const messages = useMessageRequests();
  const connections = useConnections();
  return (messages.data?.incoming?.length ?? 0) + (connections.data?.incoming?.length ?? 0);
};

/**
 * Whether this account can message anybody at all.
 *
 * Two gates, one answer, because every surface that asks wants the same thing:
 * the deployment has to offer messaging, and the account has to have answered
 * the age question. Which of the two is missing decides what the page says, so
 * callers that draw an explanation read `useDirectMessagesEnabled` as well.
 */
export const useCanUseDirectMessages = (): boolean => {
  const dmEnabled = useDirectMessagesEnabled();
  const { data } = useDmSettings();
  return dmEnabled && data !== undefined && !data.age_answer_required;
};

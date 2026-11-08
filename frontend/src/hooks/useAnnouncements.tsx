import { useLocation } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  useDismiss,
  useListAnnouncements,
  useMarkSeen,
} from "@/api/generated/announcements/announcements";
import type { AnnouncementRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { matchesTriggerRoute } from "@/lib/announcementPages";

/** Re-check for new notices about as often as the version check does. */
const REFETCH_INTERVAL = 5 * 60 * 1000;

interface UseAnnouncementsResult {
  /** The notice to show now, if any. Newest first, one at a time. */
  current: AnnouncementRead | null;
  /** How many are still queued behind `current`. */
  remaining: number;
  /** Acknowledge `current` and move to the next. */
  dismiss: (key: string) => void;
}

/**
 * Every announcement still standing, dismissed ones included: what a line in
 * the notifications opens again. A notice given an end date is not here —
 * expiry retires it, which is the difference between an end date and letting
 * a notice simply be dismissed.
 */
export const useAnnouncementArchive = (enabled: boolean) =>
  useListAnnouncements({ include_dismissed: true }, { query: { enabled } });

/**
 * The reader's side of announcements: what to show, and what they did with it.
 *
 * One at a time and newest first — a queue of dialogs stacked on each other is
 * worse than a queue of dialogs shown in turn. Being *shown* one is recorded
 * separately from acknowledging it, so a notice that was seen but left open
 * still comes back, while one that was dismissed does not.
 *
 * Two things decide whether a notice is in the queue at all:
 *
 * * **Where the reader is.** A notice with a `trigger_route` waits for a
 *   matching page and is shown there — in-context help rather than news — and
 *   is skipped everywhere else. Matching happens here because routes are a
 *   client concept; the server just carries the pattern.
 * * **How many times they have acknowledged it.** Dismissals are counted, and
 *   a notice that asked for more than one comes back until it has them.
 */
export const useAnnouncements = (enabled: boolean): UseAnnouncementsResult => {
  const pathname = useLocation({ select: (location) => location.pathname });
  const { data } = useListAnnouncements(undefined, {
    query: {
      enabled,
      refetchInterval: REFETCH_INTERVAL,
      staleTime: 60_000,
    },
  });

  // Dismissals apply here before the server confirms them: the reader clicked
  // "Got it", so the next notice should be on screen in that same frame rather
  // than after a round trip and a refetch. A notice that wants more than one
  // acknowledgement is still gone for *this* session — it returns on the next
  // fetch that finds the count short.
  const [dismissedKeys, setDismissedKeys] = useState<ReadonlySet<string>>(new Set());
  const items = useMemo(
    () =>
      (data?.items ?? []).filter((item) => {
        if (dismissedKeys.has(item.key)) return false;
        if (item.trigger_route) return matchesTriggerRoute(item.trigger_route, pathname);
        return true;
      }),
    [data, dismissedKeys, pathname]
  );
  const current = items[0] ?? null;

  const markSeen = useMarkSeen();
  const dismissMutation = useDismiss({
    mutation: {
      onSuccess: () => {
        void invalidate(q.announcements());
      },
    },
  });

  // One "seen" per key per page load: the receipt is idempotent server-side,
  // but there is no reason to send it on every render.
  const seenKeys = useRef(new Set<string>());
  const markSeenMutate = markSeen.mutate;
  useEffect(() => {
    if (!current || seenKeys.current.has(current.key)) return;
    seenKeys.current.add(current.key);
    markSeenMutate({ key: current.key });
  }, [current, markSeenMutate]);

  const dismissMutate = dismissMutation.mutate;
  const dismiss = useCallback(
    (key: string) => {
      setDismissedKeys((previous) => new Set(previous).add(key));
      dismissMutate({ key });
    },
    [dismissMutate]
  );

  return {
    current,
    remaining: Math.max(items.length - 1, 0),
    dismiss,
  };
};

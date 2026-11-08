import type {
  CommunityBillingSummaryRead,
  CommunityRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { CommunityEntry } from "@/hooks/useCommunities";
import { parseDateValue } from "@/ui/lib/formatDate";

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days left in a running trial — 0 on its last day — or null when no
 *  trial is running. Both ends are read as local calendar days. */
export const trialDaysLeft = (summary: CommunityBillingSummaryRead | undefined): number | null => {
  if (!summary?.available) return null;
  const end = parseDateValue(summary.trial_ends_on);
  if (!end) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  // Rounded, not floored: a day across a DST change is 23 or 25 hours long.
  const days = Math.round((end.getTime() - today.getTime()) / DAY_MS);
  return days >= 0 ? days : null;
};

/**
 * Whether this person may see the community's plan and open the billing
 * portal: the seat, with a session that may act on it — exactly what the
 * server's summary and handoff routes ask (`SeatWriteSessionDep`).
 *
 * A superadmin member, or support holding both a `superadmin` settings grant
 * and a `read_write` content grant: what support does with it happens in the
 * billing portal, under its own controls. A seat whose session only reads is
 * refused by the server, so it is not offered a panel that would only fail.
 */
export const holdsBillingSeat = (
  community: CommunityEntry | CommunityRead | null | undefined
): boolean => Boolean(community?.can.seat && community.can.configure);

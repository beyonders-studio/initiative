// The UI calls a community a community — see the NAMING note in `@/api/query-keys`.

import { queryOptions, skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { listAccessGrants } from "@/api/generated/access-grants/access-grants";
import {
  listCommunities,
  createCommunity as postCommunity,
  readCommunity,
  reorderCommunities as saveCommunityOrder,
} from "@/api/generated/communities/communities";
import type {
  AccessGrantRead,
  CommunityRead,
  NewCommunity,
} from "@/api/generated/initiativeAPI.schemas";
import { resetCommunityScopedQueries, setInvalidationCommunity } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  persistCommunityId,
  readStoredCommunityId,
  readStoredCommunityIdFor,
} from "@/lib/activeCommunityStorage";
import { renderableBanner } from "@/lib/banner";
import { getErrorMessage } from "@/lib/errorMessage";
import { walkPages } from "@/lib/fetchAllPages";
import { toast } from "@/lib/mascotToast";
import {
  addGrantOnlyCommunityIds,
  hydrateCommunityShard,
  isOfflineCacheEnabled,
  retainOnlyCommunities,
  setGrantOnlyCommunityIds,
} from "@/lib/offlineCache";
import {
  currentServerKey,
  isNoAnswerError,
  isSessionRejected,
  readOfflineCommunities,
  saveOfflineCommunities,
} from "@/lib/offlineSession";

/**
 * A community entry in the switcher. Member communities come from `/communities/`; entries
 * the user can only reach via a live, time-bound PAM access grant are
 * synthesized from `/access-grants/` and flagged with `accessType: "grant"`
 * so the UI can mark them temporary and enforce read-only.
 */
export type CommunityEntry = CommunityRead & {
  accessType?: "member" | "grant";
  grantExpiresAt?: string | null;
  /** The content rung of the grant this community is reached by. A settings grant
   *  carries its own vocabulary in the same field, and never gets here — a
   *  community reached only by one confers no content access to gate. */
  grantAccessLevel?: string | null;
  /** The separate settings rung held for this community. It never confers
   * content access and must not be represented as a roster role. */
  grantSettingsLevel?: "admin" | "superadmin" | null;
};

interface CommunityContextValue {
  communities: CommunityEntry[];
  /** This tab's community, taken from its `/c/{communityId}` URL (the route layout
   * calls syncCommunityFromUrl). Per-tab — no server-held context — so two tabs can
   * sit in two different communities at once. */
  activeCommunityId: number | null;
  activeCommunity: CommunityEntry | null;
  /** True when the active community is reached via a read-only grant — writes are
   * blocked server-side, so the UI should hide write affordances. */
  activeCommunityReadOnly: boolean;
  loading: boolean;
  error: string | null;
  refreshCommunities: () => Promise<CommunityEntry[]>;
  switchCommunity: (communityId: number) => Promise<void>;
  syncCommunityFromUrl: (communityId: number) => Promise<void>;
  createCommunity: (input: NewCommunity) => Promise<CommunityRead>;
  updateCommunityInState: (community: CommunityRead) => void;
  reorderCommunities: (communityIds: number[]) => void;
  canCreateCommunities: boolean;
}

export const CommunityContext = createContext<CommunityContextValue | undefined>(undefined);

const sortCommunities = (communityList: CommunityEntry[]): CommunityEntry[] => {
  return [...communityList].sort((a, b) => {
    // Grant (temporary) communities always sort after member communities.
    const aGrant = a.accessType === "grant" ? 1 : 0;
    const bGrant = b.accessType === "grant" ? 1 : 0;
    if (aGrant !== bGrant) {
      return aGrant - bGrant;
    }
    const positionDelta = (a.position ?? 0) - (b.position ?? 0);
    if (positionDelta !== 0) {
      return positionDelta;
    }
    return a.id - b.id;
  });
};

/** Build a synthetic switcher entry for a community reachable only via live grants. */
const settingsGrantLevel = (grant?: AccessGrantRead): "admin" | "superadmin" | null =>
  grant?.access_level === "admin" || grant?.access_level === "superadmin"
    ? grant.access_level
    : null;

const grantEntry = (grant: AccessGrantRead, settingsGrant?: AccessGrantRead): CommunityEntry => ({
  id: grant.community_id,
  name: grant.community_name ?? `Community #${grant.community_id}`,
  description: null,
  icon_url: null,
  location: null,
  // A blank banner until the community's own payload arrives with the real one.
  banner: renderableBanner(),
  banner_card_url: null,
  // Nobody is "here" in a community reached only by a grant until its own payload
  // arrives and says so.
  online_count: 0,
  // The rung this grant lends, as the server recorded it on the grant — the
  // community's own ladder, borrowed. A community's own payload carries the same
  // field, so a screen asks one question whichever way it was reached.
  role: settingsGrantLevel(settingsGrant) ?? "member",
  // What a content grant alone reaches: the work, and none of the community's
  // own configuration. A settings grant's answer is the community's own entry
  // (`GET /communities/{id}`); until it arrives, nothing is offered.
  can: {
    enter: true,
    content: grant.purpose === "content",
    administer: false,
    configure: false,
    administer_content: false,
    seat: false,
    // A grantee is no guest: what the grant reaches, it reaches community-wide.
    community_wide: true,
    // A grant is never reached with a personal API key.
    use_api: false,
  },
  position: Number.MAX_SAFE_INTEGER,
  display_name: null,
  retention_days: null,
  max_storage_bytes: null,
  max_users: null,
  max_guests: null,
  member_count: 0,
  tier_name: null,
  // The community's lifecycle status, so an operator on a grant sees a suspended /
  // read-only community they're acting in (the access banner surfaces it).
  status: grant.community_status,
  // PAM/break-glass overrides the lifecycle status — a grantee's writability
  // comes from the grant level, never from the community being frozen.
  content_read_only: false,
  // Only a closed community names who to contact, and a grant is never closed.
  contact_email: null,
  // Admin-only entitlements; a grantee acts as a member here, so they're absent.
  auth_options: null,
  closed_surfaces: null,
  // A grant reaches one named community directly; the directory is not how the
  // grantee got here, and this synthetic entry is never listed in it.
  is_community: false,
  categories: [],
  // Community-admin territory, and a grantee acts as a member — so, unanswered.
  has_adult_content: null,
  created_at: grant.requested_at,
  updated_at: grant.requested_at,
  accessType: "grant",
  grantExpiresAt: grant.expires_at,
  grantAccessLevel: grant.purpose === "content" ? grant.access_level : null,
  grantSettingsLevel: settingsGrantLevel(settingsGrant),
});

/**
 * A settings grant's entry, with the community's own answer laid over it: the
 * rung, what the caller may do there, and the administration fields the grant
 * does not carry. What the grant says about itself stays. Best-effort — without
 * an answer the entry changes nothing.
 */
const withSettingsEntry = async (entry: CommunityEntry): Promise<CommunityEntry> => {
  if (!entry.grantSettingsLevel) return entry;
  try {
    return {
      ...(await readCommunity(entry.id)),
      position: entry.position,
      content_read_only: entry.content_read_only,
      accessType: entry.accessType,
      grantExpiresAt: entry.grantExpiresAt,
      grantAccessLevel: entry.grantAccessLevel,
      grantSettingsLevel: entry.grantSettingsLevel,
    };
  } catch (err) {
    console.error("Failed to load the settings entry for a granted community", err);
    return entry;
  }
};

/** The switcher's list, and whether it is the one this device remembered
 *  rather than one the server gave us. */
type CommunityList = { entries: CommunityEntry[]; remembered: boolean };

/**
 * A hand-written key rather than the `/communities/` path: the entry holds that
 * answer merged with the access grants, not the endpoint's own reply, and a key
 * that is not a path is never written to the offline cache — the list this
 * device remembers is kept by `saveOfflineCommunities`, members only.
 */
const communityListKey = (userId: number | null) => ["community-switcher", userId] as const;

/**
 * Content from a community reached only by a time-bound grant is not written to the
 * offline cache, and the community list is the only thing that knows which communities
 * those are. When the grant list could not be read, the set is widened rather
 * than replaced — an incomplete reading must not shrink it.
 */
const recordGrantOnlyCommunities = (entries: CommunityEntry[], grantsKnown: boolean) => {
  const grantIds = entries
    .filter((community) => community.accessType === "grant")
    .map((community) => community.id);
  if (grantsKnown) {
    setGrantOnlyCommunityIds(grantIds);
  } else {
    addGrantOnlyCommunityIds(grantIds);
  }
};

/** A reply that came back after the account it was read for had left. */
class SupersededCommunityList extends Error {
  constructor() {
    super("The community list was read for an account no longer here");
  }
}

/**
 * Read the community list for `forUser`.
 *
 * Reads outlive the person they were made for: signing out, or switching
 * account, does not cancel a request already in the air, and acting on one now
 * means pruning this device's cache against the previous user's memberships.
 * So a reply that lands after `currentUserId` has moved on is refused.
 */
const fetchCommunityList = async (
  forUser: number,
  currentUserId: { readonly current: number | null }
): Promise<CommunityList> => {
  const superseded = () => new SupersededCommunityList();

  let listed: CommunityRead[];
  try {
    listed = await listCommunities();
  } catch (err) {
    if (currentUserId.current !== forUser) throw superseded();
    // Nothing answered: fall back to the communities this device last saw, so
    // the switcher is populated and the pages it still holds can be opened.
    // The grant list is unknown here, so the exclusion set is only widened.
    if (isOfflineCacheEnabled() && isNoAnswerError(err)) {
      // An entry an earlier build remembered carries no `can`, so it has
      // nothing to say about what may be done there and is left out.
      const remembered = readOfflineCommunities<CommunityEntry>(currentServerKey())?.filter(
        (community) => community.can !== undefined
      );
      if (remembered && remembered.length > 0) {
        const entries = sortCommunities(remembered);
        recordGrantOnlyCommunities(entries, false);
        return { entries, remembered: true };
      }
    }
    console.error("Failed to load communities", err);
    throw err;
  }
  if (currentUserId.current !== forUser) throw superseded();

  // Also surface communities the user can only reach via a live PAM grant, so they
  // appear in the switcher (flagged temporary) and can actually be entered.
  // Best-effort: a failure here must not break the community list.
  const memberIds = new Set(listed.map((g) => g.id));
  let grantCommunities: CommunityEntry[] = [];
  let grantsKnown = true;
  const liveByCommunity = new Map<
    number,
    { content?: AccessGrantRead; settings?: AccessGrantRead }
  >();
  try {
    const walked = await walkPages(listAccessGrants, { live: true, page_size: 200 });
    // A walk stopped at its bound is not every grant, so it prunes nothing.
    grantsKnown = !walked.has_next;
    const grants = walked.items;
    for (const grant of grants) {
      if (!grant.is_live || (grant.purpose !== "content" && grant.purpose !== "settings")) {
        continue;
      }
      const pair = liveByCommunity.get(grant.community_id) ?? {};
      const purpose = grant.purpose;
      const existing = pair[purpose];
      if (!existing || (grant.expires_at ?? "") > (existing.expires_at ?? "")) {
        pair[purpose] = grant;
        liveByCommunity.set(grant.community_id, pair);
      }
    }
    grantCommunities = Array.from(liveByCommunity.entries()).flatMap(
      ([communityId, { content, settings }]) => {
        if (memberIds.has(communityId)) return [];
        if (content) return [grantEntry(content, settings)];
        return settings ? [grantEntry(settings, settings)] : [];
      }
    );
    grantCommunities = await Promise.all(grantCommunities.map(withSettingsEntry));
  } catch (grantErr) {
    grantsKnown = false;
    console.error("Failed to load access grants for community switcher", grantErr);
  }

  // The grants call is a second wait, and the account can change across it.
  if (currentUserId.current !== forUser) throw superseded();

  if (isOfflineCacheEnabled()) {
    // Only real memberships are remembered for offline use: a community reached
    // by a grant has no cached content to open, and the grant may be over
    // by the time the device is looked at again.
    saveOfflineCommunities(listed, currentServerKey());
    // Both lists have to be the server's answer before anything is thrown
    // away. Without the grants half we cannot tell a community somebody has
    // left from one they are in the middle of using on a grant, so an
    // incomplete read prunes nothing and the next good one does it.
    if (grantsKnown) {
      const memberships = [...memberIds];
      await retainOnlyCommunities(
        [...memberships, ...grantCommunities.map((community) => community.id)],
        memberships
      );
    }
  }

  const memberCommunities = listed.map(
    (community): CommunityEntry => ({
      ...community,
      grantSettingsLevel: settingsGrantLevel(liveByCommunity.get(community.id)?.settings),
    })
  );
  const entries = sortCommunities([...memberCommunities, ...grantCommunities]);
  recordGrantOnlyCommunities(entries, grantsKnown);
  return { entries, remembered: false };
};

const communityListQuery = (
  userId: number | null,
  currentUserId: { readonly current: number | null }
) =>
  queryOptions({
    queryKey: communityListKey(userId),
    queryFn: userId === null ? skipToken : () => fetchCommunityList(userId, currentUserId),
    // Asked whether or not the device reports a signal: with no answer the
    // list falls back to the one this device remembered.
    networkMode: "always",
    // One account's list is never a placeholder for another's.
    placeholderData: undefined,
    // The first read decides whether the account has any community at all, so
    // a blip is asked again rather than taken as "none". Not a read for an
    // account that has left, or one the server refused the session for.
    retry: (failures, error) =>
      failures < 2 && !(error instanceof SupersededCommunityList) && !isSessionRejected(error),
  });

const NO_COMMUNITIES: CommunityEntry[] = [];

export const CommunityProvider = ({ children }: { children: ReactNode }) => {
  const queryClient = useQueryClient();
  const { user, refreshUser } = useAuth();
  const { isOnline } = useNetworkStatus();
  const [activeCommunityId, setActiveCommunityId] = useState<number | null>(readStoredCommunityId);
  const reorderDebounceRef = useRef<number | null>(null);
  const pendingOrderRef = useRef<number[] | null>(null);
  const activeCommunityIdRef = useRef(activeCommunityId);
  activeCommunityIdRef.current = activeCommunityId;
  // Mirror the active community to the invalidation layer synchronously on every
  // render (same pattern as the ref above) so community-scoped invalidation is
  // scoped from the very FIRST render — `activeCommunityId` is seeded from storage
  // by useState, so deferring this to an effect would leave a one-render window
  // where a mutation's onSuccess falls through to matching all communities. Per-tab:
  // a module var is per-JS-context (see query-keys.ts).
  setInvalidationCommunity(activeCommunityId);

  // Key community loading on the user's *id*, not the user object: `refreshUser()`
  // always returns a fresh object, so an object-identity key would refetch the
  // community list and access grants on every profile refresh.
  // A suspended account is in time out and reaches no community, so it has no
  // list to fetch: it is treated as nobody here.
  const userId = user && user.status !== "suspended" ? user.id : null;
  // Mirrored synchronously so a reply that was asked for on behalf of somebody
  // else can be recognised as such when it lands.
  const userIdRef = useRef(userId);
  userIdRef.current = userId;

  const canCreateCommunities = user?.can_create_communities ?? true;

  const communityQuery = useQuery(communityListQuery(userId, userIdRef));
  const communities = communityQuery.data?.entries ?? NO_COMMUNITIES;
  // Only the first read shows as loading, not background refreshes.
  const loading = userId !== null && communityQuery.isPending;
  // Fallback lives in the ``errors`` namespace (preloaded at init) rather than
  // ``communities``: this hook never mounts a ``useTranslation("communities")``, so on a
  // startup fetch failure that namespace may not be loaded yet.
  const error =
    userId !== null && communityQuery.error
      ? getErrorMessage(communityQuery.error, "errors:unableToLoadCommunities")
      : null;
  /** True while the switcher is showing the list this device remembered rather
   *  than one the server gave us. */
  const showingRememberedCommunitiesRef = useRef(false);
  showingRememberedCommunitiesRef.current = communityQuery.data?.remembered ?? false;

  // Persist this tab's community as the fresh-tab default (read once at mount),
  // under the account it belongs to: a browser is shared, and the next account
  // to sign in here has its own answer.
  useEffect(() => {
    persistCommunityId(activeCommunityId, userId);
  }, [activeCommunityId, userId]);

  // Keep this tab's community one the list holds. Only change it when the current
  // value is no longer valid, so an in-flight community switch is not overridden.
  const listedCommunities = communityQuery.data?.entries;
  useEffect(() => {
    if (userId === null) {
      setActiveCommunityId(null);
      return;
    }
    if (!listedCommunities) return;
    setActiveCommunityId((prev) => {
      if (prev !== null && listedCommunities.some((community) => community.id === prev)) {
        return prev;
      }
      // Fall back to what THIS account last had open, not whoever used the
      // browser before them.
      const stored = readStoredCommunityIdFor(userId);
      if (stored && listedCommunities.some((community) => community.id === stored)) {
        return stored;
      }
      // Last resort: first available community
      return listedCommunities[0]?.id ?? null;
    });
  }, [userId, listedCommunities]);

  /** Reload the community list, and hand it back: sign-in has to know what this
   *  account can reach before it decides where to land them. */
  const refreshCommunities = useCallback(async (): Promise<CommunityEntry[]> => {
    if (userId === null) {
      return [];
    }
    const options = communityListQuery(userId, userIdRef);
    // A read already under way may have started before whatever the caller
    // just changed, so it is replaced rather than joined.
    await queryClient.cancelQueries({ queryKey: options.queryKey, exact: true });
    try {
      const list = await queryClient.fetchQuery({ ...options, staleTime: 0 });
      return list.entries;
    } catch {
      return [];
    }
  }, [queryClient, userId]);

  /** Change the cached list in place, ahead of the server confirming it. */
  const editCommunities = useCallback(
    (edit: (prev: CommunityEntry[]) => CommunityEntry[]) => {
      queryClient.setQueryData<CommunityList>(
        communityListKey(userId),
        (prev) => prev && { ...prev, entries: edit(prev.entries) }
      );
    },
    [queryClient, userId]
  );

  const flushPendingOrder = useCallback(async () => {
    if (!pendingOrderRef.current) {
      return;
    }
    const payload = pendingOrderRef.current;
    pendingOrderRef.current = null;
    try {
      await saveCommunityOrder({ community_ids: payload });
    } catch (err) {
      console.error("Failed to save community order", err);
      toast.error(getErrorMessage(err, "errors:unableToSaveCommunityOrder"));
      await refreshCommunities();
    }
  }, [refreshCommunities]);

  const scheduleOrderSave = useCallback(
    (communityIds: number[]) => {
      if (communityIds.length === 0) {
        return;
      }
      pendingOrderRef.current = communityIds;
      if (typeof window === "undefined") {
        void flushPendingOrder();
        return;
      }
      if (reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      reorderDebounceRef.current = window.setTimeout(() => {
        reorderDebounceRef.current = null;
        void flushPendingOrder();
      }, 500);
    },
    [flushPendingOrder]
  );

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      if (pendingOrderRef.current) {
        void flushPendingOrder();
      }
    };
  }, [flushPendingOrder]);

  // A remembered list is only ever a stand-in. Signal returning is the moment
  // to replace it — nothing else would, since the list is fetched off the
  // user's id and that has not changed.
  useEffect(() => {
    if (!isOnline || !showingRememberedCommunitiesRef.current) return;
    void refreshCommunities();
  }, [isOnline, refreshCommunities]);

  const switchCommunity = useCallback(
    async (communityId: number) => {
      // The community lives in the URL: callers navigate to /c/{communityId} and the
      // route layout calls syncCommunityFromUrl. Here we just move this tab's local
      // state and drop the previous community's now-wrong cached query data. No
      // server context — per-tab only, so two tabs can hold different communities.
      if (userId === null || communityId === activeCommunityIdRef.current) {
        return;
      }
      setActiveCommunityId(communityId);
      await resetCommunityScopedQueries(communityId);
      await hydrateCommunityShard(communityId);
      await Promise.all([refreshCommunities(), refreshUser()]);
    },
    [userId, refreshCommunities, refreshUser]
  );

  /**
   * Adopt the community from a /c/{communityId} route into this tab's local state
   * (rail highlight, redirect targets, query keys). Per-tab only — no server
   * context — so each tab tracks the community in its own URL.
   */
  const syncCommunityFromUrl = useCallback(async (communityId: number) => {
    if (communityId === activeCommunityIdRef.current) {
      return;
    }
    setActiveCommunityId(communityId);
    persistCommunityId(communityId, userIdRef.current);
    await resetCommunityScopedQueries(communityId);
    // Only the default community is hydrated at startup, so one opened later
    // brings its own cached content with it.
    await hydrateCommunityShard(communityId);
  }, []);

  // Each browser tab holds its OWN community, taken from its `/c/{communityId}` URL —
  // tabs do NOT converge. We deliberately do not listen for the community storage
  // event, so a community switch in one tab never drags another tab's context with
  // it; that is what lets two tabs sit in two different communities at once. (The
  // persisted id is only a fresh-tab default, read once at mount.)

  const reorderCommunities = useCallback(
    (communityIds: number[]) => {
      if (communityIds.length === 0) {
        return;
      }
      if (communities.length <= 1) {
        return;
      }
      const uniqueIds: number[] = [];
      const seenIds = new Set<number>();
      for (const id of communityIds) {
        if (seenIds.has(id)) {
          continue;
        }
        seenIds.add(id);
        uniqueIds.push(id);
      }
      editCommunities((prev) => {
        if (prev.length <= 1) {
          return prev;
        }
        const lookup = new Map(prev.map((community) => [community.id, community]));
        const ordered: CommunityEntry[] = [];
        uniqueIds.forEach((id) => {
          const match = lookup.get(id);
          if (match) {
            ordered.push({ ...match });
            lookup.delete(id);
          }
        });
        ordered.push(...Array.from(lookup.values()).map((community) => ({ ...community })));
        const withPositions = ordered.map((community, index) => ({
          ...community,
          position: index,
        }));
        return sortCommunities(withPositions);
      });
      scheduleOrderSave(uniqueIds);
    },
    [communities.length, editCommunities, scheduleOrderSave]
  );

  const createCommunity = useCallback(
    async ({ name, description }: NewCommunity) => {
      if (userId === null) {
        throw new Error("You must be signed in to create a community.");
      }
      if (!canCreateCommunities) {
        throw new Error("Community creation is disabled.");
      }

      const trimmedName = name.trim();
      if (!trimmedName) {
        throw new Error("Community name is required.");
      }

      const created = await postCommunity({
        name: trimmedName,
        description: description?.trim() || undefined,
      });

      await Promise.all([refreshCommunities(), refreshUser()]);

      return created;
    },
    [userId, canCreateCommunities, refreshCommunities, refreshUser]
  );

  const updateCommunityInState = useCallback(
    (community: CommunityRead) => {
      editCommunities((prev) => {
        let replaced = false;
        const next = prev.map((existing) => {
          if (existing.id === community.id) {
            replaced = true;
            // What the entry says about how it was reached is not in the reply.
            return { ...existing, ...community };
          }
          return existing;
        });
        const merged = replaced ? next : next.concat(community);
        return sortCommunities(merged);
      });
    },
    [editCommunities]
  );

  const activeCommunity = useMemo(
    () => communities.find((community) => community.id === activeCommunityId) ?? null,
    [communities, activeCommunityId]
  );

  // Read-only when the active community is a grant that isn't read-write, OR when
  // the community's content is frozen server-side (read_only lifecycle status —
  // writes already die at the database role level; the UI must match).
  const activeCommunityReadOnly =
    (activeCommunity?.accessType === "grant" &&
      activeCommunity?.grantAccessLevel !== "read_write") ||
    Boolean(activeCommunity?.content_read_only);

  const value: CommunityContextValue = {
    communities,
    activeCommunityId,
    activeCommunity,
    activeCommunityReadOnly,
    loading,
    error,
    refreshCommunities,
    switchCommunity,
    syncCommunityFromUrl,
    createCommunity,
    updateCommunityInState,
    reorderCommunities,
    canCreateCommunities,
  };

  return <CommunityContext.Provider value={value}>{children}</CommunityContext.Provider>;
};

export const useCommunities = () => {
  const context = useContext(CommunityContext);
  if (!context) {
    throw new Error("useCommunities must be used within a CommunityProvider");
  }
  return context;
};

/**
 * The signed-in person as the active community names them: their account,
 * carrying the name they go by there (null where they set none, so the handle
 * renders). For what others see of you — a live cursor, a presence chip.
 */
export const useSelfInCommunity = () => {
  const { user } = useAuth();
  // Read without useCommunities' guard: an editor mounted outside the
  // provider names you by your handle rather than failing.
  const name = useContext(CommunityContext)?.activeCommunity?.display_name ?? null;
  return useMemo(() => (user ? { ...user, display_name: name } : null), [user, name]);
};

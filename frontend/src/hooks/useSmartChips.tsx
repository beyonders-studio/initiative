import { useQueries, useQuery } from "@tanstack/react-query";

import type {
  ReferenceEmbed,
  SearchEntityType,
  SmartChipState,
} from "@/api/generated/initiativeAPI.schemas";
import { readReferenceEmbeds, readSmartChips } from "@/api/generated/smart-chips/smart-chips";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { batchedReader } from "@/lib/batchedReader";
import { referenceRef, storedEntityType } from "@/lib/smartChips";

/**
 * How often a chip asks again with nothing having said it changed.
 *
 * The realtime bus is what keeps a chip current: a change to the thing it is
 * about marks it stale the moment it lands. This only covers what the bus
 * cannot deliver — something in an initiative this tab's socket did not join.
 */
const BACKSTOP_MS = 5 * 60_000;

/**
 * How many references one request may carry — the server's own ceilings
 * (`MAX_REFS`, `MAX_EMBEDS`), which it enforces by refusing the request rather
 * than answering part of it. A moment that asks for more sends several.
 */
export const REFS_PER_REQUEST = 500;
export const EMBEDS_PER_REQUEST = 25;

const loadChip = batchedReader<string, SmartChipState>(
  (communityId, refs) => readSmartChips(communityId, { refs }).then((answer) => answer.items),
  (state) => state.ref,
  REFS_PER_REQUEST
);

const loadEmbed = batchedReader<string, ReferenceEmbed>(
  (communityId, refs) => readReferenceEmbeds(communityId, { refs }).then((answer) => answer.items),
  (embed) => embed.ref,
  EMBEDS_PER_REQUEST
);

/** The thing a reference is about, as its cache address names it: a body
 *  saved under an earlier spelling of a kind is kept with today's. */
const subject = (ref: string) => {
  const [kind, id] = ref.split(":");
  return `${storedEntityType(kind) ?? kind}/${id}`;
};

/**
 * Where one chip's answer is kept: addressed like a read of its own, by the
 * thing it is about and then the fact, so a change to the thing names every
 * chip about it at once (`q.references(kind, id)`).
 */
export const chipKey = (communityId: number, ref: string) =>
  [`/api/v1/c/${communityId}/smart-chips/${subject(ref)}`, ref] as const;

const embedKey = (communityId: number, ref: string) =>
  [`/api/v1/c/${communityId}/smart-chips/embeds/${subject(ref)}`, ref] as const;

/** When a reading turns on its own — a due date passing, an event starting —
 *  the chip asks again at that moment, rather than on a timer. */
export const nextAsk = (state: SmartChipState | null | undefined): number => {
  const until = state?.date ? Date.parse(state.date) - Date.now() : Number.NaN;
  return until > 0 && until < BACKSTOP_MS ? until + 1_000 : BACKSTOP_MS;
};

const chipQuery = (communityId: number, ref: string, enabled = true) => ({
  queryKey: chipKey(communityId, ref),
  queryFn: () => loadChip(communityId, ref),
  enabled: enabled && communityId > 0,
  refetchInterval: (query: { state: { data?: SmartChipState | null } }) =>
    nextAsk(query.state.data),
});

/**
 * What one reference says right now, or `undefined` while it loads and where
 * it cannot be read — deleted, or never shared with this reader.
 *
 * A chip asks `task:12:status`, a link asks `task:12`. Each asks for itself;
 * the reader gathers whatever a page asks in one moment into one request.
 * `communityId` reads it in a community other than the page's, for a surface
 * that spans communities.
 */
export const useChipState = (ref: string, communityId?: number): SmartChipState | undefined => {
  const active = useActiveCommunityId();
  return useQuery(chipQuery(communityId ?? active, ref)).data ?? undefined;
};

/** The answers a list of references has so far.
 *
 * Module scope so its identity is stable: `combine` runs on every render, and
 * a fresh function here would rebuild the result each time. */
const combineStates = (results: { data?: SmartChipState | null; isFetched: boolean }[]) => ({
  states: results.flatMap((result) => (result.data ? [result.data] : [])),
  isFetched: results.every((result) => result.isFetched),
});

/** What every reference in a list says right now — for a surface that holds
 *  its references as data rather than as nodes: a list of links, a thread. */
export const useChipStates = (refs: string[], enabled = true, communityId?: number) => {
  const active = useActiveCommunityId();
  return useQueries({
    queries: refs.map((ref) => chipQuery(communityId ?? active, ref, enabled)),
    combine: combineStates,
  });
};

/** What a referenced thing is called right now, or `undefined` where it cannot
 *  be read — deleted, or never shared with this reader. */
export const useReferenceTitle = (
  entityType: SearchEntityType,
  entityId: number
): string | undefined => useChipState(referenceRef(entityType, entityId))?.text || undefined;

/**
 * What an embedded reference shows — the thing's name and its description —
 * or `null` where it cannot be read. Kept current the way a chip is: a change
 * to the thing marks it stale.
 */
export const useReferenceEmbed = (entityType: SearchEntityType, entityId: number) => {
  const communityId = useActiveCommunityId();
  const ref = referenceRef(entityType, entityId);
  return useQuery<ReferenceEmbed | null>({
    queryKey: embedKey(communityId, ref),
    queryFn: () => loadEmbed(communityId, ref),
    enabled: communityId > 0,
  });
};

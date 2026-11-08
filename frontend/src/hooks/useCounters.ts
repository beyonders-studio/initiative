import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  addCounter,
  deleteCounter,
  duplicateCounter,
  getReadCounterGroupQueryKey,
  getReadCounterQueryKey,
  resetAllCounters,
  resetCounter,
  setCounterCount,
  sortCounters,
  updateCounter,
} from "@/api/generated/counters/counters";
import type {
  CounterCreate,
  CounterGroupRead,
  CounterRead,
  CounterSetCountRequest,
  CounterSortRequest,
  CounterUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation, useOptimisticMutation } from "@/hooks/useApiMutation";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import {
  optimisticDecrement,
  optimisticIncrement,
  optimisticReset,
  optimisticSetCount,
} from "@/lib/counter-math";
import { fireCounterStepFeedback } from "@/lib/counterStepFeedback";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";
import { collator } from "@/ui/lib/intl";

// ── Optimistic update helpers ───────────────────────────────────────────────

/** `group` with one counter changed. */
const patchCounter = (
  group: CounterGroupRead,
  counterId: number,
  patch: (counter: CounterRead) => Partial<CounterRead>
): CounterGroupRead => ({
  ...group,
  counters: group.counters.map((c) => (c.id === counterId ? { ...c, ...patch(c) } : c)),
});

/**
 * One write to a group's counters: applied to the cached group at once, then
 * replaced by what the server answers with — the counter, or the whole group.
 * The lists are refetched for their previews, and the group with them.
 */
const useCounterWrite = <TData extends CounterRead | CounterGroupRead, TVariables = void>(
  groupId: number,
  mutationFn: (communityId: number, variables: TVariables) => Promise<TData>,
  apply: (group: CounterGroupRead, variables: TVariables) => CounterGroupRead,
  options?: MutationOpts<TData, TVariables>
) =>
  useOptimisticMutation<CounterGroupRead, TData, TVariables>(
    {
      queryKey: (communityId) => getReadCounterGroupQueryKey(communityId, groupId),
      apply,
      seed: (group, data) => ("counters" in data ? data : patchCounter(group, data.id, () => data)),
      mutationFn,
      invalidate: () => invalidate(q.allCounterGroups()),
      errorKey: "counterGroups:error",
    },
    options
  );

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const counterGroups = TOOL_HOOKS[Tool.counter_group];

export const useCounterGroup = counterGroups.useDetail;
export const useUpdateCounterGroup = counterGroups.useUpdate;

// ── Counter mutations ───────────────────────────────────────────────────────

export const useAddCounter = (
  groupId: number,
  options?: MutationOpts<CounterRead, CounterCreate>
) =>
  useCommunityMutation<CounterRead, CounterCreate>(
    {
      mutationFn: (communityId, data) => addCounter(communityId, groupId, data),
      invalidate: () => invalidate(q.tool(Tool.counter_group, groupId)),
      errorKey: "counterGroups:error",
    },
    options
  );

export const useDuplicateCounter = (groupId: number, options?: MutationOpts<CounterRead, number>) =>
  useCommunityMutation<CounterRead, number>(
    {
      mutationFn: (communityId, counterId) => duplicateCounter(communityId, counterId),
      invalidate: () => invalidate(q.tool(Tool.counter_group, groupId)),
      errorKey: "counterGroups:error",
    },
    options
  );

export interface UpdateCounterInput {
  counterId: number;
  data: CounterUpdate;
}

/** Generic PATCH on a counter. The patch (which may carry `position` from a
 * drag-drop) is applied at once so the cached order moves immediately. */
export const useUpdateCounter = (
  groupId: number,
  options?: MutationOpts<CounterRead, UpdateCounterInput>
) =>
  useCounterWrite(
    groupId,
    (communityId, { counterId, data }) => updateCounter(communityId, counterId, data),
    (group, { counterId, data }) =>
      patchCounter(group, counterId, () => data as Partial<CounterRead>),
    options
  );

export const useDeleteCounter = (groupId: number, options?: MutationOpts<void, number>) =>
  useOptimisticMutation<CounterGroupRead, void, number>(
    {
      queryKey: (communityId) => getReadCounterGroupQueryKey(communityId, groupId),
      apply: (group, counterId) => ({
        ...group,
        counters: group.counters.filter((c) => c.id !== counterId),
      }),
      mutationFn: (communityId, counterId) => deleteCounter(communityId, counterId),
      invalidate: () => invalidate(q.tool(Tool.counter_group, groupId)),
      errorKey: "counterGroups:error",
    },
    options
  );

// ── Value operations (all optimistic) ───────────────────────────────────────

export interface SetCountInput {
  counterId: number;
  data: CounterSetCountRequest;
}

export const useSetCount = (groupId: number, options?: MutationOpts<CounterRead, SetCountInput>) =>
  useCounterWrite(
    groupId,
    (communityId, { counterId, data }) => setCounterCount(communityId, counterId, data),
    (group, { counterId, data }) =>
      patchCounter(group, counterId, (c) => ({ count: optimisticSetCount(c, String(data.count)) })),
    options
  );

export const useResetCounter = (groupId: number, options?: MutationOpts<CounterRead, number>) =>
  useCounterWrite(
    groupId,
    (communityId, counterId) => resetCounter(communityId, counterId),
    (group, counterId) => patchCounter(group, counterId, (c) => ({ count: optimisticReset(c) })),
    options
  );

export const useResetAllCounters = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, void>
) =>
  useCounterWrite(
    groupId,
    (communityId) => resetAllCounters(communityId, groupId),
    (group) => ({
      ...group,
      counters: group.counters.map((c) => ({ ...c, count: optimisticReset(c) })),
    }),
    options
  );

/** Comparator mirroring the backend `sort_counters` service: case-insensitive
 * name (or numeric count) with `id` as a deterministic final tie-break, so the
 * optimistic order matches what the server will persist. */
const compareCounters =
  (field: CounterSortRequest["field"], direction: CounterSortRequest["direction"]) =>
  (a: CounterRead, b: CounterRead): number => {
    let cmp: number;
    if (field === "count") {
      cmp = Number(a.count) - Number(b.count);
      if (cmp === 0) cmp = collator(undefined, { sensitivity: "base" }).compare(a.name, b.name);
    } else {
      cmp = collator(undefined, { sensitivity: "base" }).compare(a.name, b.name);
    }
    if (cmp === 0) cmp = a.id - b.id;
    return direction === "desc" ? -cmp : cmp;
  };

export const useSortCounters = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, CounterSortRequest>
) =>
  useCounterWrite(
    groupId,
    (communityId, data) => sortCounters(communityId, groupId, data),
    (group, { field, direction }) => ({
      ...group,
      counters: [...group.counters]
        .sort(compareCounters(field, direction))
        .map((c, index) => ({ ...c, position: String(index + 1) })),
    }),
    options
  );

// ── Debounced stepper (button-mash coalescing) ──────────────────────────────

const STEP_DEBOUNCE_MS = 300;

/**
 * Coalesces rapid +/- clicks into a single `set` call per counter.
 *
 * Every click updates the React Query cache optimistically (so the UI is
 * instant), but the network call is debounced ~300ms behind the last click
 * and sends ONE `set` with the final value. Mashing "+" ten times yields one
 * request — `set(base + 10*step)` — instead of ten `increment` round-trips,
 * which also collapses the WebSocket broadcast storm to a single event.
 *
 * Correctness under concurrent refetches: the user's intended value is held
 * in a `pending` ref (NOT just the cache). A query-cache subscription
 * re-asserts that target over any external write — e.g. the WebSocket echo of
 * our own `set`, or a background refetch — so clicks that land *while a `set`
 * is in flight* are never clobbered by a now-stale server value. The pending
 * entry clears only once the server has confirmed the latest target.
 *
 * This is a be-polite-to-the-server optimization for well-behaved clients; it
 * is NOT an abuse defense (a hostile client can hit the endpoint directly).
 * Server-side rate limiting is the control for that.
 */
export const useSteppedCount = (groupId: number) => {
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  // counterId -> value the user is steering toward. Survives refetches until
  // the server confirms it, so in-flight clicks are never lost.
  const pending = useRef<Map<number, string>>(new Map());

  const groupKey = useMemo(
    () => getReadCounterGroupQueryKey(communityId, groupId),
    [communityId, groupId]
  );

  const applyToCache = useCallback(
    (counterId: number, value: string) => {
      queryClient.setQueryData<CounterGroupRead>(groupKey, (old) => {
        if (!old) return old;
        return {
          ...old,
          counters: old.counters.map((c) => (c.id === counterId ? { ...c, count: value } : c)),
        };
      });
    },
    [queryClient, groupKey]
  );

  const sendSet = useCallback(
    async (counterId: number) => {
      const target = pending.current.get(counterId);
      if (target === undefined) return;
      try {
        await setCounterCount(communityId, counterId, {
          count: target,
        });
        // Stop tracking only if no newer clicks landed mid-flight and nothing
        // is scheduled — otherwise the next flush owns the (newer) target.
        if (pending.current.get(counterId) === target && !timers.current.has(counterId)) {
          pending.current.delete(counterId);
        }
      } catch (error) {
        toast.error(getErrorMessage(error, "counterGroups:error"));
        pending.current.delete(counterId);
        void invalidate(q.counterGroup(groupId));
      }
    },
    [communityId, groupId]
  );

  const flush = useCallback(
    (counterId: number) => {
      timers.current.delete(counterId);
      void sendSet(counterId);
    },
    [sendSet]
  );

  const step = useCallback(
    (counter: CounterRead, direction: 1 | -1) => {
      // Fire audio + haptic per click, before any cache/network work, so
      // rapid presses feel responsive even if the debounced PUT lags.
      fireCounterStepFeedback(direction === 1 ? "up" : "down");

      // Base the next target on the in-memory intent when mid-burst (so a
      // refetch that reset the cache between presses can't lose clicks),
      // otherwise on the freshest cache value.
      const cacheGroup = queryClient.getQueryData<CounterGroupRead>(groupKey);
      const cacheCounter = cacheGroup?.counters.find((c) => c.id === counter.id) ?? counter;
      const basis: CounterRead = {
        ...cacheCounter,
        count: pending.current.get(counter.id) ?? cacheCounter.count,
      };
      const target = direction === 1 ? optimisticIncrement(basis) : optimisticDecrement(basis);

      pending.current.set(counter.id, target);
      applyToCache(counter.id, target);

      const existing = timers.current.get(counter.id);
      if (existing) clearTimeout(existing);
      timers.current.set(
        counter.id,
        setTimeout(() => flush(counter.id), STEP_DEBOUNCE_MS)
      );
    },
    [queryClient, groupKey, applyToCache, flush]
  );

  /** Drop any pending stepped flush for a counter (call before a direct set/reset). */
  const cancel = useCallback((counterId: number) => {
    const timer = timers.current.get(counterId);
    if (timer) clearTimeout(timer);
    timers.current.delete(counterId);
    pending.current.delete(counterId);
  }, []);

  const cancelAll = useCallback(() => {
    for (const timer of timers.current.values()) clearTimeout(timer);
    timers.current.clear();
    pending.current.clear();
  }, []);

  // Re-assert pending targets over any external cache write (WebSocket echo,
  // background refetch) so in-flight clicks survive until the server confirms
  // the latest value. Guard with size === 0 so the common idle case is cheap,
  // and ignore cache events for any query other than this group's so unrelated
  // app-wide mutations during a click burst don't trigger the comparison loop.
  useEffect(() => {
    const cache = queryClient.getQueryCache();
    const groupKeyHash = JSON.stringify(groupKey);
    const unsubscribe = cache.subscribe((event) => {
      if (pending.current.size === 0) return;
      if (JSON.stringify(event.query.queryKey) !== groupKeyHash) return;
      const data = queryClient.getQueryData<CounterGroupRead>(groupKey);
      if (!data) return;
      let changed = false;
      const counters = data.counters.map((c) => {
        const target = pending.current.get(c.id);
        if (target !== undefined && c.count !== target) {
          changed = true;
          return { ...c, count: target };
        }
        return c;
      });
      if (changed) {
        queryClient.setQueryData<CounterGroupRead>(groupKey, { ...data, counters });
      }
    });
    return unsubscribe;
  }, [queryClient, groupKey]);

  // Flush trailing edits on unmount so navigating away doesn't drop them.
  useEffect(() => {
    const timerMap = timers.current;
    const pendingMap = pending.current;
    return () => {
      for (const [counterId, timer] of timerMap) {
        clearTimeout(timer);
        const target = pendingMap.get(counterId);
        if (target !== undefined) {
          void setCounterCount(communityId, counterId, {
            count: target,
          });
        }
      }
      timerMap.clear();
      pendingMap.clear();
    };
  }, [communityId, groupId]);

  return {
    increment: (counter: CounterRead) => step(counter, 1),
    decrement: (counter: CounterRead) => step(counter, -1),
    cancel,
    cancelAll,
  };
};

export type SteppedCount = ReturnType<typeof useSteppedCount>;

/** How a group's counters are saved field by field. */
export const counterSaves = (groupId: number): FieldSaveKind<CounterRead, CounterUpdate> => ({
  name: "counter",
  readKey: (communityId, id) => getReadCounterQueryKey(communityId, id),
  patch: (communityId, id, patch) => updateCounter(communityId, id, patch),
  properties: PropertyTarget.counter,
  lists: () => q.tool(Tool.counter_group, groupId),
  itself: (id) => q.counter(id),
});

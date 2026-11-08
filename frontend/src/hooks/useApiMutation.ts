import { onlineManager, type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";

import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";

/**
 * Shared config for the domain mutation hooks.
 *
 * `mutationFn` must return `Promise<TData>` — the Orval-generated fetchers are
 * genuinely typed (the Axios mutator unwraps `.data` and is typed to match),
 * so a mismatch here means the hook's declared type disagrees with the API
 * schema and should be fixed, not cast away.
 */
interface ApiMutationConfig<TData, TVariables> {
  /** Perform the request. The runtime result is the unwrapped payload. */
  mutationFn: (variables: TVariables) => Promise<TData>;
  /**
   * The hook's own work on success (invalidations, cache writes, its success
   * toast), done before the caller's `onSuccess`. Receives the mutation result
   * and variables; the return value is not awaited (fire-and-forget, matching
   * the hand-written hooks).
   */
  invalidate?: (data: TData, variables: TVariables) => unknown;
  /** `getErrorMessage` fallback key for the error toast, raised only while
   *  online. Omit to skip the toast. */
  errorKey?: string;
}

/**
 * Base mutation hook for personal/platform endpoints: composes the caller's
 * `onSuccess`/`onError`/`onSettled` with the hook's invalidation + error toast.
 */
export function useApiMutation<TData, TVariables = void, TContext = unknown>(
  config: ApiMutationConfig<TData, TVariables>,
  options?: MutationOpts<TData, TVariables, Error, TContext>
) {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation<TData, Error, TVariables, TContext>({
    ...rest,
    mutationFn: (variables) => config.mutationFn(variables),
    // The caller's own work is waited on, but its failure is not the save's.
    //
    // React Query waits on what `onSuccess` returns before it calls a mutation
    // settled, and dropping it let the Save button come back while a caller's
    // follow-up was still in flight — long enough to press it again, which for
    // an item whose tags and links go in requests of their own means saving it
    // twice. So it is returned.
    //
    // Returned *settled*, though: a caller that follows a save by refreshing
    // something would otherwise have a failed refresh reported as a failed
    // save, and be told to retry a change that already landed. What happens
    // after the write is the caller's to report — several already do — and all
    // this needs from it is how long to stay pending.
    //
    // Settled, not swallowed: it is written down, because a follow-up that
    // quietly fails leaves the screen showing something the server no longer
    // says, and nothing else would ever mention it.
    onSuccess: (...args) => {
      void config.invalidate?.(args[0], args[1]);
      const following = onSuccess?.(...args);
      return following instanceof Promise
        ? following.catch((error: unknown) => {
            console.error("Work after a successful save did not finish:", error);
          })
        : following;
    },
    onError: (...args) => {
      // Offline, the offline banner already says why a write failed.
      if (config.errorKey && onlineManager.isOnline()) {
        toast.error(getErrorMessage(args[0], config.errorKey));
      }
      onError?.(...args);
    },
    onSettled,
  });
}

interface CommunityMutationConfig<TData, TVariables> {
  /** Perform the request against the active community (from the route path). */
  mutationFn: (communityId: number, variables: TVariables) => Promise<TData>;
  invalidate?: (data: TData, variables: TVariables) => unknown;
  errorKey?: string;
}

/**
 * Community-scoped variant of {@link useApiMutation}: threads the active community id
 * (derived from the `/c/{communityId}` route) into `mutationFn`. Domain hooks stay
 * as thin named wrappers so their public signatures are unchanged.
 */
export function useCommunityMutation<TData, TVariables = void, TContext = unknown>(
  config: CommunityMutationConfig<TData, TVariables>,
  options?: MutationOpts<TData, TVariables, Error, TContext>
) {
  const communityId = useActiveCommunityId();
  return useApiMutation<TData, TVariables, TContext>(
    {
      ...config,
      mutationFn: (variables) => config.mutationFn(communityId, variables),
    },
    options
  );
}

interface OptimisticMutationConfig<TCached, TData, TVariables>
  extends CommunityMutationConfig<TData, TVariables> {
  /** The cached read the write changes. */
  queryKey: (communityId: number) => QueryKey;
  /** What that read shows while the write is in flight. */
  apply: (cached: TCached, variables: TVariables) => TCached;
  /** What it shows once the server answers. Omit to keep the optimistic copy
   *  until `invalidate` refetches it. */
  seed?: (cached: TCached, data: TData) => TCached;
}

/**
 * {@link useCommunityMutation} that shows its result before the server does:
 * `apply` writes the cached read at once, a failure puts the previous copy
 * back and refetches it, and the answer is written over it with `seed`.
 */
export function useOptimisticMutation<TCached, TData, TVariables = void>(
  { queryKey, apply, seed, ...config }: OptimisticMutationConfig<TCached, TData, TVariables>,
  options?: MutationOpts<TData, TVariables>
) {
  const communityId = useActiveCommunityId();
  const client = useQueryClient();
  const key = queryKey(communityId);
  const { onMutate: _ownedHere, onError, ...rest } = options ?? {};

  return useCommunityMutation<TData, TVariables, { previous?: TCached }>(
    {
      ...config,
      invalidate: (data, variables) => {
        if (seed) {
          client.setQueryData<TCached>(key, (cached) =>
            cached === undefined ? cached : seed(cached, data)
          );
        }
        return config.invalidate?.(data, variables);
      },
    },
    {
      ...rest,
      // Not awaited: the abort goes out at once, so a refetch already in
      // flight cannot land over the copy written below.
      onMutate: (variables) => {
        void client.cancelQueries({ queryKey: key });
        const previous = client.getQueryData<TCached>(key);
        if (previous !== undefined) client.setQueryData<TCached>(key, apply(previous, variables));
        return { previous };
      },
      onError: (error, variables, context, mutationContext) => {
        if (context?.previous !== undefined) client.setQueryData(key, context.previous);
        // The copy put back predates any change that landed meanwhile.
        void client.invalidateQueries({ queryKey: key });
        onError?.(error, variables, context, mutationContext);
      },
    }
  );
}

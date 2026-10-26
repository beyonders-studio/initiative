/**
 * Saving an item's fields one at a time, for any kind of item a page edits
 * field by field: a task, an event. What an edit names shows at once and is
 * taken back if it fails, and one item's saves go out one at a time in the
 * order they were made, so the last change made is the one the server keeps.
 */

import {
  type QueryClient,
  type QueryKey,
  type UseQueryResult,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyTarget, PropertyValueInput } from "@/api/generated/initiativeAPI.schemas";
import { setProperties } from "@/api/generated/properties/properties";
import { describes, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import type { FieldSave, FieldSaveState } from "@/lib/layouts/editing";
import { toast } from "@/lib/mascotToast";
import { currentServerKey } from "@/lib/offlineSession";

/** A change to some of an item's fields: what is sent, and how the item reads
 *  once it is saved. A change to its properties names only those it sets or
 *  takes off, so one person's leaves another's standing. */
export type ItemEdit<I, P> = { shows: Partial<I> } & (
  | { patch: P }
  | { properties: { values: PropertyValueInput[]; removed?: number[] } }
);

/** One field's save, as {@link useItemFieldSave} answers it. */
export type ItemFieldSave<I, P> = FieldSave & {
  save: (edit: ItemEdit<I, P>, undo?: ItemEdit<I, P>) => Promise<boolean>;
  error: unknown;
  reset: () => void;
};

/**
 * An item being added, which nothing has saved yet: its fields' saves change
 * the copy the dialog holds, and Add makes it whole.
 */
export interface ItemDraft {
  /** Takes in one field's change. */
  edit: (edit: ItemEdit<unknown, unknown>) => void;
  /** Adds it, as Enter in a typed field does. */
  submit: () => void;
  /** Whether the field `id` shows a value it cannot take (a number left
   *  empty), which Add waits for. */
  hold: (id: string, holding: boolean) => void;
}

export const ItemDraftContext = createContext<ItemDraft | null>(null);

/** How one kind of item is saved field by field. */
export interface FieldSaveKind<I, P> {
  /** Names the kind in its saves' keys. */
  name: string;
  /** The item's own read in the cache. */
  readKey: (communityId: number, id: number) => QueryKey;
  /** Sends a patch, answering with the item as the server now holds it. */
  patch: (communityId: number, id: number, patch: P) => Promise<Partial<I>>;
  /** Where its properties are set. */
  properties: PropertyTarget;
  /** The lists showing the item that a saved edit makes stale. */
  lists: (edit: ItemEdit<I, P>) => Spec;
  /** The item's own read, read afresh once its last save settles. */
  itself: (id: number) => Spec;
}

/** What one kind's page adds to a save. */
export interface FieldSaveOptions<I, P> {
  /** What an edit needs asked before it is sent (which of a series it is
   *  for), answering the edit to send, or null to send none. */
  prepare?: (edit: ItemEdit<I, P>) => Promise<ItemEdit<I, P> | null>;
  /** The edit Undo sends for `undo`, given the edit it takes back. */
  undoWith?: (undo: ItemEdit<I, P>, edit: ItemEdit<I, P>) => ItemEdit<I, P>;
  /** What the confirmation offering Undo says; by default, that the field was
   *  cleared. */
  undoMessage?: (edit: ItemEdit<I, P>) => string | undefined;
  /** Runs as an edit is sent, for what it shows as made at once. */
  sending?: (edit: ItemEdit<I, P>) => void;
  /** Runs when an edit is saved, by Save or by Retry. */
  onSaved?: (edit: ItemEdit<I, P>) => void;
  /** Whether the answer is another item, which the page moves to (one date
   *  of a repeating event made its own): it is not written over this one. */
  movedTo?: (written: Partial<I>) => boolean;
}

const SAVED_SHOWN_MS = 2_000;

/** One save of some of an item's fields, as the mutation that sends it carries it. */
interface FieldSaveCall<I, P> {
  communityId: number;
  id: number;
  edit: ItemEdit<I, P>;
  /** The edit the confirmation's Undo sends. */
  undo?: ItemEdit<I, P>;
  /** Who sent it, to which server. Its answer is written only while both still hold. */
  session: { userId: number | undefined; server: string };
}

/** Every save of one item's fields shares this key, whichever field it is. */
const fieldSaveKey = (name: string, communityId: number, id: number) =>
  [`${name}-field`, communityId, id] as const;

/** The item's field saves not yet answered: being sent, or waiting their turn. */
const pendingFieldSaves = <I, P>(
  client: QueryClient,
  name: string,
  communityId: number,
  id: number
): FieldSaveCall<I, P>[] =>
  client
    .getMutationCache()
    .findAll({ mutationKey: fieldSaveKey(name, communityId, id), exact: true, status: "pending" })
    .map((mutation) => mutation.state.variables as FieldSaveCall<I, P>);

/**
 * The item as `data` holds it, with its field saves not yet answered shown
 * over it, in the order they were made, which is the order they land in.
 */
export const usePendingShown = <I, P>(
  kind: FieldSaveKind<I, P>,
  id: number | null,
  data: I | undefined
): I | undefined => {
  const communityId = useActiveCommunityId();
  const pending = useMutationState({
    filters: {
      mutationKey: fieldSaveKey(kind.name, communityId, id ?? 0),
      exact: true,
      status: "pending",
    },
    select: (mutation) => (mutation.state.variables as FieldSaveCall<I, P>).edit.shows,
  });
  return useMemo(
    () => (data && pending.length ? Object.assign({ ...data }, ...pending) : data),
    [data, pending]
  );
};

/** Where {@link useHeldItem} keeps an item's answered saves: the read key of
 *  a save kind for items with no read of their own. */
export const heldKey = (name: string, communityId: number, id: number) =>
  ["held", name, communityId, id] as const;

/** The copy of the item a held answer was answered over. */
const OVER = Symbol("over");

type Held<I> = I & { [OVER]?: I };

/**
 * An item as the page passed it, or as a save of it answered over that same
 * copy, with saves not yet answered shown over either: for an item with no
 * read of its own (one the queue's or the catalog's read carries), whose save
 * kind's read key is {@link heldKey}. An answer stands until the page passes
 * a newer copy: the one it was answered over (a dialog opened again on what it
 * held) does not undo it. For a kind with a read of its own, it is `item`.
 */
export const useHeldItem = <I extends object, P>(
  kind: FieldSaveKind<I, P>,
  id: number,
  item: I
): I => {
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  const key = heldKey(kind.name, communityId, id);
  const fresh = (): Held<I> => ({ ...item, [OVER]: item });
  const { data } = useQuery({
    queryKey: key,
    queryFn: () => queryClient.getQueryData<Held<I>>(key) ?? fresh(),
    staleTime: Number.POSITIVE_INFINITY,
    // Sharing rebuilds the item from its keys, which would drop the mark of
    // the copy it was answered over.
    structuralSharing: false,
  });
  const held = data?.[OVER] === item ? data : item;
  useEffect(() => {
    const key = heldKey(kind.name, communityId, id);
    if (queryClient.getQueryData<Held<I>>(key)?.[OVER] !== item) {
      queryClient.setQueryData<Held<I>>(key, { ...item, [OVER]: item });
    }
  }, [queryClient, kind.name, communityId, id, item]);
  return usePendingShown(kind, id, held) ?? item;
};

/** {@link usePendingShown} over the item as `query` read it. */
export const useShownWithPending = <I, P>(
  kind: FieldSaveKind<I, P>,
  id: number | null,
  query: UseQueryResult<I>
): UseQueryResult<I> => {
  const data = usePendingShown(kind, id, query.data);
  return data === query.data ? query : ({ ...query, data } as UseQueryResult<I>);
};

/**
 * The one way an item's page saves a field: the fields it names, shown at
 * once and taken back if it fails.
 *
 * Given `undo`, the edit that puts it back, the confirmation offers Undo.
 *
 * Each save is a mutation keyed by its item, and one item's saves are sent one
 * at a time in the order they were made. The cached item holds only what the
 * server answered; {@link useShownWithPending} shows the saves not yet
 * answered over it, so a failed save leaves nothing to take back, and a newer
 * save of the same field keeps showing. The item is read afresh once the last
 * save settles. An answer that lands after its session ended (signed out, or
 * another server) writes nothing.
 */
export const useItemFieldSave = <I, P>(
  kind: FieldSaveKind<I, P>,
  id: number,
  label: string,
  options: FieldSaveOptions<I, P> = {}
): ItemFieldSave<I, P> => {
  const { t } = useTranslation("common");
  const drafting = useContext(ItemDraftContext);
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [state, setState] = useState<FieldSaveState>("idle");
  const [error, setError] = useState<unknown>(null);
  const sending = useRef(0);
  const last = useRef<{ edit: ItemEdit<I, P>; undo?: ItemEdit<I, P> } | null>(null);
  // Another item (a panel moved to another row) starts with nothing to retry:
  // what failed was the last item's.
  useEffect(() => {
    last.current = null;
    setState("idle");
    setError(null);
  }, [kind.name, communityId, id]);
  // Who is signed in now, for answers that land later.
  const signedIn = useRef(user?.id);
  useEffect(() => {
    signedIn.current = user?.id;
  });

  useEffect(() => {
    if (state !== "saved") return;
    const timer = setTimeout(() => setState("idle"), SAVED_SHOWN_MS);
    return () => clearTimeout(timer);
  }, [state]);

  /** The item's saves in flight, while `save` still belongs to this session;
   *  null once it does not. Clearing the cache on sign-out drops it from them. */
  const inSession = (save: FieldSaveCall<I, P>): FieldSaveCall<I, P>[] | null => {
    const { userId, server } = save.session;
    if (userId !== signedIn.current || server !== currentServerKey()) return null;
    const pending = pendingFieldSaves<I, P>(queryClient, kind.name, save.communityId, save.id);
    return pending.includes(save) ? pending : null;
  };

  const cancelReads = ({ communityId, id }: Pick<FieldSaveCall<I, P>, "communityId" | "id">) =>
    queryClient.cancelQueries({ queryKey: kind.readKey(communityId, id), exact: true });

  const { mutateAsync } = useMutation({
    mutationKey: fieldSaveKey(kind.name, communityId, id),
    // One at a time per item, in the order made: a later save waits its turn.
    scope: { id: `${kind.name}-field:${communityId}:${id}` },
    mutationFn: async ({ edit, ...save }: FieldSaveCall<I, P>): Promise<Partial<I>> => {
      // A read already in flight may have been answered before this write,
      // and would land over it. Runs when this save's turn comes, not when
      // it was queued.
      await cancelReads(save);
      return "patch" in edit
        ? kind.patch(save.communityId, save.id, edit.patch)
        : // Every kind that has properties reads them as `properties`.
          ({
            properties: await setProperties(save.communityId, kind.properties, save.id, {
              ...edit.properties,
              merge: true,
            }),
          } as unknown as Partial<I>);
    },
    onSuccess: async (written, save) => {
      if (!inSession(save)) return;
      const { edit, undo } = save;
      // So does a read started while this save was being sent.
      await cancelReads(save);
      const moved = options.movedTo?.(written) ?? false;
      // Every earlier save has landed, so this answer is what the server holds.
      if (!moved) {
        queryClient.setQueryData<I>(
          kind.readKey(save.communityId, save.id),
          (current) => current && { ...current, ...written }
        );
      }
      // The lists showing the item; the item itself is read once the last save settles.
      const lists = describes(kind.lists(edit));
      const itself = describes(kind.itself(save.id));
      void queryClient.invalidateQueries({
        predicate: ({ queryKey }) => lists(queryKey) && !itself(queryKey),
      });
      // A change that became another item's is undone there, not here.
      if (undo && !moved) {
        toast.success(options.undoMessage?.(edit) ?? t("fieldSave.cleared", { field: label }), {
          action: {
            label: t("fieldSave.undo"),
            onClick: () => void send(options.undoWith?.(undo, edit) ?? undo),
          },
        });
      }
      options.onSaved?.(edit);
    },
    onSettled: (_written, _failed, save) => {
      // Only this save is left: what the server holds now is what to show.
      if (inSession(save)?.length === 1) {
        void queryClient.invalidateQueries({
          queryKey: kind.readKey(save.communityId, save.id),
          exact: true,
        });
      }
    },
  });

  const send = async (edit: ItemEdit<I, P>, undo?: ItemEdit<I, P>): Promise<boolean> => {
    last.current = { edit, undo };
    sending.current += 1;
    setState("saving");
    setError(null);
    options.sending?.(edit);
    let saved = false;
    try {
      await mutateAsync({
        communityId,
        id,
        edit,
        undo,
        session: { userId: user?.id, server: currentServerKey() },
      });
      saved = true;
    } catch (failed) {
      setError(failed);
    }
    sending.current -= 1;
    if (sending.current === 0) setState(saved ? "saved" : "error");
    return saved;
  };

  const save = async (edit: ItemEdit<I, P>, undo?: ItemEdit<I, P>): Promise<boolean> => {
    const prepared = options.prepare ? await options.prepare(edit) : edit;
    return prepared === null ? false : send(prepared, undo);
  };

  // An item being added holds what is changed until Add.
  if (drafting) {
    return {
      state: "idle",
      retry: () => {},
      error: null,
      reset: () => {},
      save: async (edit) => {
        drafting.edit(edit as ItemEdit<unknown, unknown>);
        return true;
      },
    };
  }
  const field: FieldSave = {
    state,
    retry: () => {
      if (last.current) void send(last.current.edit, last.current.undo);
    },
  };
  return {
    ...field,
    save,
    error,
    reset: () => {
      setError(null);
      setState("idle");
    },
  };
};

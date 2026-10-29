import { useQueries, useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type TaskPriority, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getListTagsQueryKey, listTags } from "@/api/generated/tags/tags";
import { getListTaskTypesQueryOptions } from "@/api/generated/task-types/task-types";
import { getSearchUsersQueryOptions } from "@/api/generated/users/users";
import { useAuth } from "@/hooks/useAuth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  handlesIn,
  readTitle,
  type TitleContext,
  type TitlePerson,
  type TitleReading,
  type TitleWords,
  titleWords,
  WORD_KEYS,
} from "@/lib/smartTitle";

const PRIORITIES: TaskPriority[] = ["low", "medium", "high", "urgent"];

/** Whether the reader has a new task's title read for its details. */
export const useSmartTitlesOn = (): boolean => useAuth().user?.smart_task_titles !== false;

/** The words a title is read with, in the reader's language. */
export const useTitleWords = (): TitleWords => {
  const { t, i18n } = useTranslation("tasks");
  const locale = i18n.language;
  return useMemo(
    () =>
      titleWords(
        Object.fromEntries(
          WORD_KEYS.map((key) => [key, t(`smartTitle.words.${key}` as never) as string])
        ) as Record<(typeof WORD_KEYS)[number], string>,
        Object.fromEntries(
          PRIORITIES.map((priority) => [priority, t(`priority.${priority}` as never) as string])
        ) as Record<TaskPriority, string>,
        locale
      ),
    [t, locale]
  );
};

export interface SmartTitle {
  /** What the title says; null while it is not being read. */
  reading: TitleReading | null;
  /** Reads another text the same way, for a change not yet drawn. */
  read: (text: string) => TitleReading;
  /** Keeps these parts as typed. */
  keep: (keys: string[]) => void;
  /** Somebody picked from the list under `@`, who their handle now names. */
  picked: (person: TitlePerson) => void;
  /** Starts over for the next task: nothing kept, nobody picked. */
  reset: () => void;
}

/**
 * Reads a new task's `text` for its details: the community's tags for `#`,
 * the project's task types for a leading "bug:", and for `@` the people who
 * can open the project, looked up as their handles are typed.
 */
export const useSmartTitle = ({
  text,
  communityId,
  projectId,
  enabled,
}: {
  text: string;
  communityId: number | null | undefined;
  projectId: number;
  enabled: boolean;
}): SmartTitle => {
  const { user } = useAuth();
  const words = useTitleWords();
  const [kept, setKept] = useState<ReadonlySet<string>>(() => new Set());
  const [chosen, setChosen] = useState<TitlePerson[]>([]);
  const hasCommunity = communityId != null;

  const tags = useQuery({
    queryKey: getListTagsQueryKey(communityId ?? 0),
    queryFn: () => listTags(communityId ?? 0),
    staleTime: 60 * 1000,
    enabled: enabled && hasCommunity && text.includes("#"),
  });

  const types = useQuery({
    ...getListTaskTypesQueryOptions(communityId ?? 0, projectId),
    staleTime: 60 * 1000,
    enabled: enabled && hasCommunity && text.includes(":"),
  });

  // Looked up once typing pauses, rather than for every letter of a name.
  const handles = useDebouncedValue(enabled ? handlesIn(text).join(" ") : "", 250);
  const found = useQueries({
    queries: [...new Set(handles.split(" ").filter(Boolean))].map((handle) =>
      getSearchUsersQueryOptions(
        communityId ?? 0,
        {
          search: handle.split("#")[0],
          page_size: 20,
          tool: Tool.project,
          resource_id: projectId,
        },
        { query: { enabled: hasCommunity, staleTime: 30_000 } }
      )
    ),
  });
  const peopleKey = found.map((query) => query.dataUpdatedAt).join(",");
  // biome-ignore lint/correctness/useExhaustiveDependencies: the queries' answers change only with their update times
  const people = useMemo(() => {
    // Somebody picked from the list is who their name means, beside anybody
    // else who goes by it.
    // One person found by two handles' searches is still one person.
    const byId = new Map<number, TitlePerson>();
    for (const person of found.flatMap((query) => query.data?.items ?? []) as TitlePerson[]) {
      byId.set(person.id, person);
    }
    const others = [...byId.values()].filter(
      (person) => !chosen.some((each) => each.username === person.username && each.id !== person.id)
    );
    return [...chosen, ...others.filter((person) => !chosen.some((c) => c.id === person.id))];
  }, [peopleKey, chosen]);

  const me = useMemo<TitlePerson | null>(
    () =>
      user
        ? {
            id: user.id,
            username: user.username,
            discriminator: user.discriminator,
            display_name: null,
            avatar_url: user.avatar_url ?? null,
            status: user.status,
          }
        : null,
    [user]
  );

  const context = useMemo<Omit<TitleContext, "now">>(
    () => ({
      words,
      weekStartsOn: user?.week_starts_on ?? 0,
      tags: tags.data ?? [],
      types: types.data ?? [],
      people,
      me,
      kept,
    }),
    [words, user?.week_starts_on, tags.data, types.data, people, me, kept]
  );
  const read = useCallback(
    (typed: string) => readTitle(typed, { ...context, now: new Date() }),
    [context]
  );
  const reading = useMemo(() => (enabled ? read(text) : null), [enabled, read, text]);
  const keep = useCallback(
    (keys: string[]) => setKept((previous) => new Set([...previous, ...keys])),
    []
  );
  const picked = useCallback(
    (person: TitlePerson) =>
      setChosen((previous) => [
        ...previous.filter((each) => each.username !== person.username),
        person,
      ]),
    []
  );
  const reset = useCallback(() => {
    setKept(new Set());
    setChosen([]);
  }, []);
  return { reading, read, keep, picked, reset };
};

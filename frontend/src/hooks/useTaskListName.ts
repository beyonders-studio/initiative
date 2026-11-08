import { useReadProject } from "@/api/generated/projects/projects";
import type { HomeTaskList } from "@/lib/home/firstHome";

/**
 * The name of a list a home widget adds to, read from the list itself rather
 * than kept with the widget: the reader's preferences hold where it is, never
 * what anybody called it. Nothing comes back for a list that is gone or no
 * longer theirs to read, which is how a widget knows to stop offering it.
 */
export const useTaskListName = (list: HomeTaskList | null) =>
  useReadProject(list?.communityId ?? 0, list?.projectId ?? 0, undefined, {
    query: {
      enabled: list !== null,
      staleTime: 5 * 60_000,
      retry: false,
      select: (project) => project.name,
    },
  });

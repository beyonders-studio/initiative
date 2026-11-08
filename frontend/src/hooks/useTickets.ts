/**
 * Filing a ticket — asking for help, reporting something.
 *
 * One way in for every kind. Whether a kind can be filed from where the reader
 * is, or only written to by email, or neither, is the server's one answer per
 * kind; nothing here reasons about bindings or entitlements.
 */

import type {
  AppealTicketCreate,
  FeedbackTicketCreate,
  FiledTicketDetailRead,
  FiledTicketList,
  ModerationTicketCreate,
  SecurityTicketCreate,
  SupportTicketCreate,
  TaskRead,
  TicketAccepted,
  TicketAvailability,
} from "@/api/generated/initiativeAPI.schemas";
import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadTaskCaseQueryKey,
  takeTaskCase,
  useReadTaskCase,
} from "@/api/generated/tasks/tasks";
import {
  fileTicket,
  getReadFiledTicketQueryKey,
  replyToFiledTicket,
  useListFiledTickets,
  useReadFiledTicket,
  useReadTicketAvailability,
} from "@/api/generated/tickets/tickets";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation, useCommunityMutation } from "@/hooks/useApiMutation";
import { docsUrl } from "@/lib/links";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Where somebody is sent when there is neither a form nor an address. */
export const FAQ_URL = docsUrl("faq/");

/** A ticket's one line at most this long, as the column behind it. */
export const SUBJECT_MAX = 200;

/** The help a person asks for about a community, rather than themselves. */
export const COMMUNITY_TOPICS: ReadonlySet<string> = new Set([
  SupportTopic.community,
  SupportTopic.data_request,
]);

/** A help request's one line, from the start of what somebody wrote. */
export const firstLine = (text: string) => {
  const line = text.trim().split("\n")[0]?.trim() ?? "";
  return line.length > SUBJECT_MAX ? `${line.slice(0, SUBJECT_MAX - 1)}…` : line;
};

/** One filing, told apart by its stream, and an appeal by its type. */
export type TicketCreate =
  | SupportTicketCreate
  | ModerationTicketCreate
  | SecurityTicketCreate
  | FeedbackTicketCreate
  | AppealTicketCreate;

/** A filing and the files sent with it. */
export interface TicketFiling {
  ticket: TicketCreate;
  files: File[];
}

/** An answer and the files sent with it. */
export interface TicketAnswer {
  body: string;
  files: File[];
}

/**
 * What every kind of ticket offers the reader, standing in `communityId`.
 *
 * Asked once per community and left alone: what a deployment has set up does
 * not change while somebody is looking at a sidebar, and a wrong answer costs
 * a refusal the form already handles.
 */
export const useTicketAvailability = (
  communityId: number | null,
  options?: QueryOpts<TicketAvailability>
) => {
  const params = communityId == null ? undefined : { community_id: communityId };
  return useReadTicketAvailability(params, { query: { staleTime: 5 * 60 * 1000, ...options } });
};

export const useFileTicket = (options?: MutationOpts<TicketAccepted, TicketFiling>) =>
  useApiMutation<TicketAccepted, TicketFiling>(
    {
      // The ticket travels as JSON beside the files: one multipart body.
      mutationFn: ({ ticket, files }) => fileTicket({ payload: JSON.stringify(ticket), files }),
      // A filing with somebody to answer it joins the reader's own tickets.
      invalidate: () => invalidate(q.filedTickets()),
    },
    options
  );

/** The tickets the reader filed, most recently moved first. */
export const useFiledTickets = (options?: QueryOpts<FiledTicketList>) =>
  useListFiledTickets({ query: options });

/** One ticket the reader filed, with what has been said to them about it. */
export const useFiledTicket = (taskId: number, options?: QueryOpts<FiledTicketDetailRead>) =>
  useReadFiledTicket(taskId, { query: options });

/** Answer on a ticket the reader filed. The answer comes back as the ticket. */
export const useReplyToTicket = (
  taskId: number,
  options?: MutationOpts<FiledTicketDetailRead, TicketAnswer>
) =>
  useApiMutation<FiledTicketDetailRead, TicketAnswer>(
    {
      mutationFn: ({ body, files }) => replyToFiledTicket(taskId, { body, files }),
      invalidate: (ticket) => {
        queryClient.setQueryData(getReadFiledTicketQueryKey(taskId), ticket);
        return invalidate(q.filedTickets());
      },
      errorKey: "intake:tickets.replyError",
    },
    options
  );

/** The case behind a task in the active community, for the people working it.
 *  A task no stream opened answers 404, which is the usual answer. */
export const useTaskCase = (taskId: number) => {
  const communityId = useActiveCommunityId();
  return useReadTaskCase(communityId, taskId, {
    query: {
      enabled: Number.isFinite(taskId),
      // Most tasks are not cases: a 404 is the usual answer, not a failure.
      retry: false,
    },
  });
};

/** Read the case behind ``taskId`` again: its conversation moved. */
export const refreshTaskCase = (taskId: number, communityId?: number) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [path] = query.queryKey as [unknown];
      return (
        typeof path === "string" &&
        (communityId == null
          ? path.endsWith(`/tasks/${taskId}/case`)
          : path === getReadTaskCaseQueryKey(communityId, taskId)[0])
      );
    },
  });

/** Take an operations case: the reader is assigned beside whoever has it,
 *  and a case waiting to be picked up is put to work. */
export const useTakeCase = (options?: MutationOpts<TaskRead, number>) =>
  useCommunityMutation<TaskRead, number>(
    {
      mutationFn: (communityId, taskId) => takeTaskCase(communityId, taskId),
      invalidate: (_task, taskId) =>
        Promise.all([invalidate(q.allTasks(), q.task(taskId)), refreshTaskCase(taskId)]),
      errorKey: "intake:case.takeFailed",
    },
    options
  );

/** Whether the reader has filed anything worth a page of its own. */
export const useHasFiledTickets = () => {
  const { data } = useFiledTickets({ staleTime: 5 * 60 * 1000 });
  return (data?.items.length ?? 0) > 0;
};

const FILED_TICKET = /^\/api\/v1\/me\/tickets\/\d+$/;

/**
 * Read the reader's tickets again: the list, and any one of them open on a
 * page. What the account socket's ticket frame asks for — it names nothing,
 * so everything of theirs is read again through the filer routes.
 */
export const refreshFiledTickets = () =>
  Promise.all([
    invalidate(q.filedTickets()),
    queryClient.invalidateQueries({
      predicate: (query) => {
        const [path] = query.queryKey as [unknown];
        return typeof path === "string" && FILED_TICKET.test(path);
      },
    }),
  ]);

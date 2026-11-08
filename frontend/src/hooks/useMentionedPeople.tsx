/**
 * Who a mention names, now.
 *
 * A mention stores an id and nothing else about the person. What a reader
 * should see is who that id is *now* — and a mention needs more than a name to
 * be a link: the handle a profile is addressed by is the username and the
 * number together, neither of which is written into the mention.
 *
 * Each mention asks for its own person, and the asks a page makes in one
 * moment go out together — the reader smart chips use — so a thread of forty
 * comments naming the same three people asks about three people, once.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { getSearchUsersQueryKey, searchUsers } from "@/api/generated/users/users";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { USER_ID_LOOKUP_MAX } from "@/hooks/useUsers";
import { batchedReader } from "@/lib/batchedReader";

let personReader: ((communityId: number, userId: number) => Promise<UserSummary | null>) | null =
  null;

/** One person, through the page's batched lookup — made on first use, so
 *  loading this module asks nothing of the member hooks it reads from. */
const loadPerson = (communityId: number, userId: number) => {
  personReader ??= batchedReader<number, UserSummary>(
    (community, userIds) =>
      searchUsers(community, { user_id: userIds, page_size: USER_ID_LOOKUP_MAX }).then(
        (page) => page.items
      ),
    (person) => person.id,
    USER_ID_LOOKUP_MAX
  );
  return personReader(communityId, userId);
};

/** One person, read in the community the mention was written in: that is who
 *  they are there, and whether they are still there at all. Kept under the
 *  member search's own address, so whatever refreshes the members refreshes
 *  the names they are mentioned by. */
const personQuery = (communityId: number, userId: number) => ({
  queryKey: [...getSearchUsersQueryKey(communityId), { mentioned: userId }],
  queryFn: () => loadPerson(communityId, userId),
  enabled: communityId > 0,
});

/**
 * The community the mentions below were written in, where that is not the one
 * the page is in — a task's description shown outside its community.
 */
export const MentionCommunity = createContext<number | null>(null);

/** Where a mention is read: the community it names, the one it sits in, or
 *  the page's. */
const useMentionCommunity = (communityId: number | undefined) => {
  const written = useContext(MentionCommunity);
  const active = useActiveCommunityId();
  return communityId ?? written ?? active;
};

/** Who a mentioned id is, or `undefined` while the answer is on its way — and
 *  for good once `ready` says it is not coming. `communityId` is the community
 *  the mention was written in, where that is not the one the page is in. */
export const useMentionedPerson = (
  userId: number | null | undefined,
  communityId?: number
): { person: UserSummary | undefined; ready: boolean; failed: boolean } => {
  const community = useMentionCommunity(communityId);
  const query = useQuery({
    ...personQuery(community, userId ?? 0),
    enabled: userId != null && community > 0,
  });
  return {
    person: query.data ?? undefined,
    ready: userId == null || query.isSuccess,
    failed: query.isError,
  };
};

/** The answers so far, by id.
 *
 * Module scope so its identity is stable: `combine` runs on every render. */
const combinePeople = (results: { data?: UserSummary | null }[]) =>
  new Map(results.flatMap(({ data }) => (data ? [[data.id, data] as const] : [])));

/** Everyone in a list of ids — for a surface that writes names into its own
 *  text rather than drawing a mention for each. */
export const useMentionedPeople = (userIds: number[], communityId?: number) => {
  const community = useMentionCommunity(communityId);
  return useQueries({
    queries: userIds.map((userId) => personQuery(community, userId)),
    combine: combinePeople,
  });
};

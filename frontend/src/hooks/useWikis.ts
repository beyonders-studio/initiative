import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import type {
  WikiPageCreate,
  WikiPageMove,
  WikiPageRead,
  WikiPageTree,
  WikiPageUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  addFileToWiki,
  createWikiPage,
  deleteWikiPage,
  duplicateWikiPage,
  getListWikiPagesQueryKey,
  getReadWikiPageQueryKey,
  listWikiPages,
  moveWikiFile,
  moveWikiPage,
  readWikiPage,
  removeFileFromWiki,
  updateWikiPage,
} from "@/api/generated/wikis/wikis";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunityPath } from "@/lib/communityUrl";
import { wikiPageRoute } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const wikis = TOOL_HOOKS[Tool.wiki];
export const useWiki = wikis.useDetail;
export const useUpdateWiki = wikis.useUpdate;
export const useDeleteWiki = wikis.useDelete;
export const useSetWikiGrants = wikis.useSetGrants;

// ── A wiki's pages ──────────────────────────────────────────────────────────

/**
 * Every page of a wiki, flat and in reading order.
 *
 * One query for the whole tree, because the navigation draws all of it — and
 * the rows carry no bodies, so this stays small however much has been written.
 */
export const useWikiPages = (wikiId: number | null, options?: QueryOpts<WikiPageTree>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<WikiPageTree>({
    queryKey: getListWikiPagesQueryKey(communityId, wikiId!),
    queryFn: () => listWikiPages(communityId, wikiId!),
    enabled: wikiId !== null && Number.isFinite(wikiId) && userEnabled,
    ...rest,
  });
};

export const useWikiPage = (pageId: number | null, options?: QueryOpts<WikiPageRead>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const ready = pageId !== null && Number.isFinite(pageId);
  return useQuery<WikiPageRead>({
    queryKey: getReadWikiPageQueryKey(communityId, pageId!),
    queryFn: () => readWikiPage(communityId, pageId!),
    enabled: ready && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, WikiPageCreate>
) =>
  useCommunityMutation<WikiPageRead, WikiPageCreate>(
    {
      mutationFn: (communityId, data) => createWikiPage(communityId, wikiId, data),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

/**
 * The "New page" action: makes a page and opens it for writing, because a
 * page nobody has written yet has nothing to read.
 */
export const useAddWikiPage = (wikiId: number, initiativeId: number) => {
  const gp = useCommunityPath();
  const navigate = useNavigate();
  return useCreateWikiPage(wikiId, {
    onSuccess: (page) =>
      void navigate({
        to: gp(wikiPageRoute(initiativeId, wikiId, page.id)),
        search: { edit: true },
      }),
  });
};

export const useDuplicateWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, number>
) =>
  useCommunityMutation<WikiPageRead, number>(
    {
      mutationFn: (communityId, pageId) => duplicateWikiPage(communityId, pageId),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

/**
 * Put an existing file in this wiki, or take it back out.
 *
 * Neither writes the file. A file joins a wiki by an edge, so what
 * changes is what the wiki contains — which is why both invalidate the page
 * list, and nothing belonging to the file itself.
 */
export const useAddWikiFile = (wikiId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, fileId) => addFileToWiki(communityId, wikiId, fileId),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useRemoveWikiFile = (wikiId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, fileId) => removeFileFromWiki(communityId, wikiId, fileId),
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useUpdateWikiPage = (
  wikiId: number,
  pageId: number,
  options?: MutationOpts<WikiPageRead, WikiPageUpdate>
) =>
  useCommunityMutation<WikiPageRead, WikiPageUpdate>(
    {
      mutationFn: (communityId, data) => updateWikiPage(communityId, pageId, data),
      // A rename changes the tree, and a body edit changes what links out of
      // this page — so both the tree and the connections are stale.
      invalidate: () => invalidate(q.wikiPages(wikiId), q.relationships()),
      errorKey: "wikis:error",
    },
    options
  );

/** Which row of the list is being moved, and where it now goes. The row
 *  travels in the variables rather than in the hook, because a drag names it
 *  at the moment it ends — a hook bound to a row would still be bound to the
 *  last one. */
export type MoveWikiPageVars = WikiPageMove & { pageId: number };

export const useMoveWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, MoveWikiPageVars>
) =>
  useCommunityMutation<WikiPageRead, MoveWikiPageVars>(
    {
      mutationFn: (communityId, { pageId, ...move }) => moveWikiPage(communityId, pageId, move),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export type MoveWikiFileVars = WikiPageMove & { fileId: number };

/** A borrowed file is a row of the same list, so it moves the same way —
 *  the wiki records where it put it, and the file is not touched. */
export const useMoveWikiFile = (wikiId: number, options?: MutationOpts<void, MoveWikiFileVars>) =>
  useCommunityMutation<void, MoveWikiFileVars>(
    {
      mutationFn: (communityId, { fileId, ...move }) =>
        moveWikiFile(communityId, wikiId, fileId, move),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useDeleteWikiPage = (wikiId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, pageId) =>
        deleteWikiPage(communityId, pageId).then(() => undefined),
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

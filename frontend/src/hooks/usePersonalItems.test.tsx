/**
 * Opening a tool records it for the header's tabs bar. The bar is read across
 * every community the reader is in, so a reopen moves the tab rather than
 * reading the bar again. Opening something inside a tool is recorded too, and
 * never touches the bar.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { type ReactNode, useEffect, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { buildRecentItem } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  ListedMark,
  type PersonalItemRead,
  ViewSource,
} from "@/api/generated/initiativeAPI.schemas";
import { getListMyPersonalItemsQueryKey } from "@/api/generated/personal-items/personal-items";
import { useRecordOpen, useRecordRecentView } from "@/hooks/usePersonalItems";
import { queryClient } from "@/lib/queryClient";
import { FROM_SEARCH } from "@/lib/searchResults";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

const VIEWED_AT = "2026-09-30T12:00:00.000Z";

/** Every open the server is told of, as `kind id source`. */
const recordOpens = () => {
  const opened: string[] = [];
  server.use(
    communityHttp.put("/personal-items/view/:entityType/:entityId", ({ request, params }) => {
      const source = new URL(request.url).searchParams.get("source") ?? "direct";
      opened.push(`${params.entityType} ${params.entityId} ${source}`);
      return HttpResponse.json({
        entity_type: params.entityType,
        entity_id: Number(params.entityId),
        viewed_at: VIEWED_AT,
        view_source: source,
      });
    })
  );
  return opened;
};

describe("useRecordRecentView", () => {
  afterEach(() => queryClient.clear());

  it("moves a reopened tab to the front, and reads the bar again only for a new one", async () => {
    const key = getListMyPersonalItemsQueryKey({ mark: ListedMark.view });
    const [first, reopened] = [
      buildRecentItem({ viewed_at: "2026-09-30T11:00:00.000Z" }),
      buildRecentItem({ viewed_at: "2026-09-30T10:00:00.000Z" }),
    ];
    queryClient.setQueryData<PersonalItemRead[]>(key, [first, reopened]);
    server.use(
      communityHttp.put("/personal-items/view/:entityType/:entityId", ({ params }) =>
        HttpResponse.json({
          entity_type: "project",
          entity_id: Number(params.entityId),
          viewed_at: VIEWED_AT,
        })
      )
    );
    const { result } = renderHook(() => useRecordRecentView("project", reopened.community_id), {
      wrapper,
    });

    result.current.mutate(reopened.entity_id);

    await waitFor(() =>
      expect(queryClient.getQueryData(key)).toEqual([{ ...reopened, viewed_at: VIEWED_AT }, first])
    );
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);

    // An answer for an earlier view, arriving last, does not jump the queue.
    server.use(
      communityHttp.put("/personal-items/view/:entityType/:entityId", ({ params }) =>
        HttpResponse.json({
          entity_type: "project",
          entity_id: Number(params.entityId),
          viewed_at: "2026-09-30T11:30:00.000Z",
        })
      )
    );
    result.current.mutate(first.entity_id);

    await waitFor(() =>
      expect(queryClient.getQueryData(key)).toEqual([
        { ...reopened, viewed_at: VIEWED_AT },
        { ...first, viewed_at: "2026-09-30T11:30:00.000Z" },
      ])
    );

    result.current.mutate(reopened.entity_id + 100);

    await waitFor(() => expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true));
  });

  it("records something inside a tool with where it was opened from, leaving the bar alone", async () => {
    const opened = recordOpens();
    // As a page reads it: the task it shows stays the one before until the
    // next one's answer arrives.
    const TaskPage = () => {
      const { taskId } = useParams({ strict: false }) as { taskId: string };
      const [shown, setShown] = useState<number>();
      useEffect(() => {
        const answer = setTimeout(() => setShown(Number(taskId)), 30);
        return () => clearTimeout(answer);
      }, [taskId]);
      useRecordOpen("task", shown);
      return null;
    };
    const key = getListMyPersonalItemsQueryKey({ mark: ListedMark.view });
    const bar = [buildRecentItem()];
    queryClient.setQueryData(key, bar);
    const { router } = renderPage(TaskPage, {
      queryClient,
      initialRoute: "/c/$communityId/tasks/$taskId",
      routeParams: { communityId: "3", taskId: "7" },
    });

    await waitFor(() => expect(opened).toEqual(["task 7 direct"]));

    // Searching for what is already open opens it again.
    await router.navigate({ href: "/c/3/tasks/7", state: FROM_SEARCH });
    await waitFor(() => expect(opened).toEqual(["task 7 direct", "task 7 search"]));

    // Searching for another records that one, not the one being left; moving
    // about on a page opens nothing.
    await router.navigate({ href: "/c/3/tasks/8", state: FROM_SEARCH });
    await waitFor(() => expect(opened).toHaveLength(3));
    await router.navigate({ href: "/c/3/tasks/8?tab=details" });
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(opened).toEqual(["task 7 direct", "task 7 search", "task 8 search"]);

    // A page that corrects its own address is still at what is open.
    await router.navigate({ href: "/c/30/tasks/8", replace: true });
    await new Promise((resolve) => setTimeout(resolve, 50));
    await router.navigate({ href: "/c/30/tasks/8", state: FROM_SEARCH });
    await waitFor(() => expect(opened).toHaveLength(4));
    expect(opened[3]).toBe("task 8 search");
    expect(queryClient.getQueryData(key)).toBe(bar);
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);
  });

  it("records a tool again for each thing opened in it, and an open inside a page as direct", async () => {
    const opened = recordOpens();
    const WikiPage = () => {
      const { pageId } = useParams({ strict: false }) as { pageId: string };
      const { image } = useSearch({ strict: false }) as { image?: string };
      useRecordOpen("wiki", 4, { each: Number(pageId) });
      useRecordOpen("catalog_item", image ? Number(image) : undefined, {
        source: ViewSource.direct,
      });
      return null;
    };
    const { router } = renderPage(WikiPage, {
      queryClient,
      initialRoute: "/c/$communityId/wikis/4/pages/$pageId",
      routeParams: { communityId: "3", pageId: "1" },
      routerSearch: { image: "9" },
    });
    await waitFor(() => expect(opened.sort()).toEqual(["catalog_item 9 direct", "wiki 4 direct"]));

    await router.navigate({ href: "/c/3/wikis/4/pages/2" });
    await waitFor(() => expect(opened).toHaveLength(3));
    await router.navigate({ href: "/c/3/wikis/4/pages/2", state: FROM_SEARCH });
    await waitFor(() => expect(opened).toHaveLength(4));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(opened.slice(2)).toEqual(["wiki 4 direct", "wiki 4 search"]);

    // Closing the image and opening it again is another open.
    await router.navigate({ href: "/c/3/wikis/4/pages/2?tab=info" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    await router.navigate({ href: "/c/3/wikis/4/pages/2?image=9" });
    await waitFor(() => expect(opened).toHaveLength(5));
    expect(opened[4]).toBe("catalog_item 9 direct");
  });
});

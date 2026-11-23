/**
 * The vocabulary is kept until the community's installs change.
 *
 * Its datasets are the installed tools', so a tool plug-in installed while a
 * dashboard is open has to reach the builder without a reload, and nothing
 * else should ask for it again.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { setInvalidationCommunity } from "@/api/query-keys";
import { useInstallCommunityPlugin } from "@/hooks/useCommunityPlugins";
import { queryClient } from "@/lib/queryClient";

import { useQueryVocabulary } from "./useQueryVocabulary";

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 1 }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

let datasets: string[] = [];
let asked = 0;

beforeEach(() => {
  queryClient.clear();
  setInvalidationCommunity(1);
  datasets = ["projects", "tasks"];
  asked = 0;
  server.use(
    communityHttp.get("/query/vocabulary", () => {
      asked += 1;
      return HttpResponse.json({ datasets, functions: [], tokens: [] });
    }),
    communityHttp.post("/plugins/", () => {
      datasets = ["hoard_items", "projects", "tasks"];
      return HttpResponse.json({});
    })
  );
});

afterEach(() => {
  queryClient.clear();
  setInvalidationCommunity(null);
});

it("lists a tool plug-in's datasets once it is installed", async () => {
  const { result } = renderHook(
    () => ({ vocabulary: useQueryVocabulary(), install: useInstallCommunityPlugin() }),
    { wrapper }
  );
  await waitFor(() => expect(result.current.vocabulary.datasets).toEqual(["projects", "tasks"]));

  await act(() => result.current.install.mutateAsync({ listing_uid: "HOARD000000001" }));

  await waitFor(() =>
    expect(result.current.vocabulary.datasets).toEqual(["hoard_items", "projects", "tasks"])
  );
  expect(asked).toBe(2);
});

/**
 * The first read of the community list decides whether the account has any
 * community at all — and with none, the app shows the start flow meant for a
 * new account. A read that failed once is therefore asked again before it is
 * reported, and a failure is never handed on as an empty list.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildPage, buildUser } from "@/__tests__/factories";
import { createTestQueryClient } from "@/__tests__/helpers/render";

const get = vi.fn();

// Generated calls arrive here, answered by path through `get`.
vi.mock("@/api/mutator", () => ({
  apiMutator: ({ url, params }: { url: string; params?: unknown }) => {
    const path = url.replace(/^\/api\/v1/, "");
    return (params ? get(path, { params }) : get(path)).then((r: { data: unknown }) => r.data);
  },
}));

vi.mock("@/api/query-keys", () => ({
  setInvalidationCommunity: vi.fn(),
  resetCommunityScopedQueries: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => false,
  setGrantOnlyCommunityIds: vi.fn(),
  addGrantOnlyCommunityIds: vi.fn(),
  hydrateCommunityShard: vi.fn().mockResolvedValue(undefined),
  retainOnlyCommunities: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/offlineSession", () => ({
  currentServerKey: () => "https://initiative.example",
  isNoAnswerError: () => false,
  isSessionRejected: (error: { response?: { status?: number } }) => error?.response?.status === 401,
  readOfflineCommunities: () => null,
  saveOfflineCommunities: vi.fn(),
}));

const user = buildUser();
const refreshUser = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user, refreshUser }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: true }),
}));

import { CommunityProvider, useCommunities } from "./useCommunities";

const Probe = () => {
  const { communities, loading, error } = useCommunities();
  return (
    <div data-testid="state">
      {loading ? "loading" : error ? "error" : `listed:${communities.length}`}
    </div>
  );
};

const renderProvider = (child: ReactNode = <Probe />) => {
  const client = createTestQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<CommunityProvider>{child}</CommunityProvider>, { wrapper });
};

const serverError = (status: number) =>
  Object.assign(new Error("failed"), { response: { status } });

const communityCalls = () => get.mock.calls.filter(([path]) => path === "/communities/").length;

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the first read of the community list", () => {
  it("is asked again after a failure, and stays loading meanwhile", async () => {
    let communityReads = 0;
    get.mockImplementation((path: string) => {
      if (path === "/access-grants/") return Promise.resolve({ data: buildPage([]) });
      communityReads += 1;
      return communityReads === 1
        ? Promise.reject(serverError(502))
        : Promise.resolve({ data: [buildCommunity({ id: 7 })] });
    });

    renderProvider();

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByTestId("state")).toHaveTextContent("loading");

    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(screen.getByTestId("state")).toHaveTextContent("listed:1");
    expect(communityCalls()).toBe(2);
  });

  it("reports an error, not an empty list, once it gives up", async () => {
    get.mockImplementation(() => Promise.reject(serverError(503)));

    renderProvider();

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByTestId("state")).toHaveTextContent("error");
    expect(communityCalls()).toBe(3);
  });

  it("is not asked again when the server refused the session", async () => {
    get.mockImplementation(() => Promise.reject(serverError(401)));

    renderProvider();

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByTestId("state")).toHaveTextContent("error");
    expect(communityCalls()).toBe(1);
  });
});

describe("the community provider", () => {
  it("hands its readers the same value when nothing they read changed", async () => {
    get.mockImplementation((path: string) =>
      Promise.resolve({
        data: path === "/access-grants/" ? buildPage([]) : [buildCommunity({ id: 7 })],
      })
    );
    let renders = 0;
    const Reader = () => {
      useCommunities();
      renders += 1;
      return null;
    };
    const reader = <Reader />;
    const { rerender } = renderProvider(reader);
    await act(() => vi.advanceTimersByTimeAsync(0));
    const settled = renders;

    rerender(<CommunityProvider>{reader}</CommunityProvider>);

    expect(renders).toBe(settled);
  });
});

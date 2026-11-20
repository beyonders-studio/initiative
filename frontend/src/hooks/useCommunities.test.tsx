/**
 * The community list the provider reads, and what it does with it.
 *
 * The first read decides whether the account has any community at all — and
 * with none, the app shows the start flow meant for a new account. A read that
 * failed once is therefore asked again before it is reported, and a failure is
 * never handed on as an empty list.
 *
 * Reads also outlive the person they were made for: signing out, or switching
 * account, does not cancel a request already in the air, and once the list
 * drives what gets deleted from this device, the previous user's memberships
 * must not decide what the current one keeps.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildPage, buildUser, communityCan } from "@/__tests__/factories";
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

/** Flipped per test: the offline cache is native-only. */
let offlineEnabled = false;
const retainOnlyCommunities = vi.fn().mockResolvedValue(undefined);
const saveOfflineCommunities = vi.fn();

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => offlineEnabled,
  setGrantOnlyCommunityIds: vi.fn(),
  addGrantOnlyCommunityIds: vi.fn(),
  hydrateCommunityShard: vi.fn().mockResolvedValue(undefined),
  retainOnlyCommunities: (...args: unknown[]) => retainOnlyCommunities(...args),
}));

vi.mock("@/lib/offlineSession", () => ({
  currentServerKey: () => "https://initiative.example",
  isNoAnswerError: () => false,
  isSessionRejected: (error: { response?: { status?: number } }) => error?.response?.status === 401,
  readOfflineCommunities: () => null,
  saveOfflineCommunities: (...args: unknown[]) => saveOfflineCommunities(...args),
}));

let currentUser: ReturnType<typeof buildUser> | null = null;
const refreshUser = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: currentUser, refreshUser }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: true }),
}));

import { CommunityProvider, useCommunities } from "./useCommunities";

/** The provider reads its list through React Query, so each render gets a client. */
const renderProvider = (child: ReactNode) => {
  const client = createTestQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<CommunityProvider>{child}</CommunityProvider>, { wrapper });
};

beforeEach(() => {
  vi.clearAllMocks();
  offlineEnabled = false;
  currentUser = buildUser();
});

const Probe = () => {
  const { communities, loading, error } = useCommunities();
  return (
    <div data-testid="state">
      {loading ? "loading" : error ? "error" : `listed:${communities.length}`}
    </div>
  );
};

const serverError = (status: number) =>
  Object.assign(new Error("failed"), { response: { status } });

const communityCalls = () => get.mock.calls.filter(([path]) => path === "/communities/").length;

describe("the first read of the community list", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("is asked again after a failure, and stays loading meanwhile", async () => {
    let communityReads = 0;
    get.mockImplementation((path: string) => {
      if (path === "/access-grants/") return Promise.resolve({ data: buildPage([]) });
      communityReads += 1;
      return communityReads === 1
        ? Promise.reject(serverError(502))
        : Promise.resolve({ data: [buildCommunity({ id: 7 })] });
    });

    renderProvider(<Probe />);

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByTestId("state")).toHaveTextContent("loading");

    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(screen.getByTestId("state")).toHaveTextContent("listed:1");
    expect(communityCalls()).toBe(2);
  });

  it("reports an error, not an empty list, once it gives up", async () => {
    get.mockImplementation(() => Promise.reject(serverError(503)));

    renderProvider(<Probe />);

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByTestId("state")).toHaveTextContent("error");
    expect(communityCalls()).toBe(3);
  });

  it("is not asked again when the server refused the session", async () => {
    get.mockImplementation(() => Promise.reject(serverError(401)));

    renderProvider(<Probe />);

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(screen.getByTestId("state")).toHaveTextContent("error");
    expect(communityCalls()).toBe(1);
  });

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

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

describe("a community list that arrives for the wrong account", () => {
  it("is not allowed to prune this device against the previous user", async () => {
    const first = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(first.promise);

    offlineEnabled = true;
    const view = renderProvider(<div />);

    await waitFor(() => expect(get).toHaveBeenCalledWith("/communities/"));

    // Somebody else is here now, and their own read is already under way.
    currentUser = buildUser();
    get.mockImplementation((path: string) =>
      Promise.resolve({
        data: path === "/access-grants/" ? buildPage([]) : [buildCommunity({ id: 99 })],
      })
    );
    view.rerender(
      <CommunityProvider>
        <div />
      </CommunityProvider>
    );

    // Only now does the first account's reply come back.
    first.resolve({ data: [buildCommunity({ id: 1 }), buildCommunity({ id: 2 })] });

    await waitFor(() => expect(retainOnlyCommunities).toHaveBeenCalled());

    // Every prune must be for the account that is actually here.
    for (const call of retainOnlyCommunities.mock.calls) {
      expect(call[1]).not.toEqual(expect.arrayContaining([1, 2]));
    }
    // And the stale list is not written down as what this device should hold.
    for (const call of saveOfflineCommunities.mock.calls) {
      const ids = (call[0] as Array<{ id: number }>).map((community) => community.id);
      expect(ids).not.toContain(1);
    }
  });
});

const GrantProbe = () => {
  const { activeCommunity } = useCommunities();
  return (
    <output>
      {JSON.stringify({
        content: activeCommunity?.grantAccessLevel,
        settings: activeCommunity?.grantSettingsLevel,
      })}
    </output>
  );
};

/** A live grant on community 8. */
const grant = (purpose: "content" | "settings", access_level: string) => ({
  community_id: 8,
  community_name: "Granted Community",
  purpose,
  access_level,
  is_live: true,
  requested_at: "2026-09-17T20:00:00Z",
  expires_at: "2026-09-17T21:00:00Z",
});

describe("settings grants in the community switcher", () => {
  it("preserves settings authority separately from content authority", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: buildPage([grant("content", "read_write"), grant("settings", "superadmin")]),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    renderProvider(<GrantProbe />);

    await waitFor(() =>
      expect(screen.getByText('{"content":"read_write","settings":"superadmin"}')).toBeVisible()
    );
  });

  it("reads every page of live grants", async () => {
    get.mockImplementation((path: string, config?: { params?: { page?: number } }) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/" && config?.params?.page === 1) {
        return Promise.resolve({ data: buildPage([], { has_next: true }) });
      }
      if (path === "/access-grants/" && config?.params?.page === 2) {
        return Promise.resolve({
          data: buildPage([grant("content", "read")], { page: 2, has_prev: true }),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    renderProvider(<GrantProbe />);

    await waitFor(() =>
      expect(screen.getByText('{"content":"read","settings":null}')).toBeVisible()
    );
    expect(get).toHaveBeenCalledWith("/access-grants/", {
      params: { live: true, page: 2, page_size: 200 },
    });
  });

  it("keeps a settings grant alongside an ordinary membership", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") {
        return Promise.resolve({ data: [buildCommunity({ id: 8, role: "member" })] });
      }
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: buildPage([grant("settings", "superadmin")]),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    renderProvider(<GrantProbe />);

    await waitFor(() => expect(screen.getByText('{"settings":"superadmin"}')).toBeVisible());
  });

  it("takes what may be changed from the community's own entry", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: buildPage([grant("settings", "admin")]),
        });
      }
      if (path === "/communities/8") {
        return Promise.resolve({
          data: buildCommunity({
            id: 8,
            role: "admin",
            can: communityCan("admin", {
              content: false,
              configure: false,
              administer_content: false,
            }),
            retention_days: 30,
          }),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    const EntryProbe = () => {
      const { activeCommunity } = useCommunities();
      return (
        <output>
          {JSON.stringify({
            access: activeCommunity?.accessType,
            settings: activeCommunity?.grantSettingsLevel,
            can: activeCommunity?.can,
            retention: activeCommunity?.retention_days,
          })}
        </output>
      );
    };

    renderProvider(<EntryProbe />);

    await waitFor(() =>
      expect(
        screen.getByText(
          JSON.stringify({
            access: "grant",
            settings: "admin",
            can: communityCan("admin", {
              content: false,
              configure: false,
              administer_content: false,
            }),
            retention: 30,
          })
        )
      ).toBeVisible()
    );
    expect(get).toHaveBeenCalledWith("/communities/8");
  });
});

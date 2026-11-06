import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { buildCommunity } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { AppLayout } from "./_authenticated";

// The layout is mounted directly, as `$communityId.test.tsx` mounts its own:
// what is under test is which screen it picks for a given community list, so
// the app-wide side effects it starts are stubbed out, and so is the start
// flow, which only has to be recognisable.
vi.mock("@/components/start/StartFlow", () => ({
  StartFlow: () => <div data-testid="start-flow" />,
}));
vi.mock("@/hooks/useFinishPendingStart", () => ({ useFinishPendingStart: () => undefined }));
vi.mock("@/hooks/useVersionCheck", () => ({
  useVersionCheck: () => ({ updateAvailable: { show: false, version: "" }, closeDialog: vi.fn() }),
}));
vi.mock("@/hooks/useRealtimeUpdates", () => ({ useRealtimeUpdates: () => undefined }));
vi.mock("@/hooks/useNotificationStream", () => ({ useNotificationStream: () => undefined }));
vi.mock("@/hooks/usePushNotifications", () => ({
  usePushNotifications: () => undefined,
  usePushTray: () => undefined,
}));
vi.mock("@/hooks/useDesktopApp", () => ({ useDesktopApp: () => undefined }));
vi.mock("@/hooks/useBackButton", () => ({ useBackButton: () => undefined }));
vi.mock("@/hooks/useShareTarget", () => ({ useResumePendingShare: () => undefined }));
vi.mock("@/hooks/useMyMessages", () => ({
  useCollectMessagesWhereRegistered: () => undefined,
}));
vi.mock("@/hooks/usePersonalItems", () => ({
  useRecents: () => ({ data: [], isLoading: false }),
  useClearRecentView: () => ({ mutate: vi.fn() }),
  useClearRecentViews: () => ({ mutate: vi.fn() }),
}));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

const show = ({
  error = null as string | null,
  communities = [] as ReturnType<typeof buildCommunity>[],
  refreshCommunities = vi.fn().mockResolvedValue([]),
} = {}) => {
  renderPage(AppLayout, {
    communities: {
      communities,
      activeCommunityId: null,
      activeCommunity: null,
      loading: false,
      error,
      refreshCommunities,
    },
  });
  return refreshCommunities;
};

describe("signing in when the community list could not be read", () => {
  it("does not greet the account as a new one", async () => {
    show({ error: "Unable to load communities." });

    expect(await screen.findByText("Couldn't load your communities")).toBeInTheDocument();
    expect(screen.queryByTestId("start-flow")).not.toBeInTheDocument();
  });

  it("asks again on Try again, and stays put if that fails too", async () => {
    const pending = deferred<never[]>();
    const refresh = show({
      error: "Unable to load communities.",
      refreshCommunities: vi.fn().mockReturnValue(pending.promise),
    });

    const retry = await screen.findByRole("button", { name: "Try again" });
    await userEvent.click(retry);

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(retry).toBeDisabled();

    // The second read failed as well: the list is still unknown, so the same
    // screen stays, ready to be asked again.
    pending.resolve([]);
    await waitFor(() => expect(retry).toBeEnabled());
    expect(screen.getByText("Couldn't load your communities")).toBeInTheDocument();
    expect(screen.queryByTestId("start-flow")).not.toBeInTheDocument();
  });
});

describe("signing in with no communities", () => {
  it("shows the start flow when the server said there are none", async () => {
    show();

    expect(await screen.findByTestId("start-flow")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load your communities")).not.toBeInTheDocument();
  });
});

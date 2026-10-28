import type {
  InfiniteData,
  UseInfiniteQueryResult,
  UseMutationResult,
  UseQueryResult,
} from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  GrantCaseList,
  PlatformCommunityStorageRead,
} from "@/api/generated/initiativeAPI.schemas";

const createRequest = vi.fn();
const breakGlass = vi.fn();
/** The ceiling the server reports for the caller's requests. */
let requestCeiling = 240;

/** What every read the page makes has come back as: loaded, nothing in flight. */
const settled = {
  dataUpdatedAt: 0,
  error: null,
  errorUpdatedAt: 0,
  failureCount: 0,
  failureReason: null,
  errorUpdateCount: 0,
  isError: false,
  isFetched: true,
  isFetchedAfterMount: true,
  isFetching: false,
  isLoading: false,
  isPending: false,
  isLoadingError: false,
  isInitialLoading: false,
  isPaused: false,
  isPlaceholderData: false,
  isRefetchError: false,
  isRefetching: false,
  isStale: false,
  isSuccess: true,
  isEnabled: true,
  status: "success",
  fetchStatus: "idle",
} as const;

/** A read that answered with this. */
const answered = <TData,>(data: TData): UseQueryResult<TData, Error> => ({
  ...settled,
  data,
  refetch: vi.fn(),
});

/** A paged list that answered with no pages at all. */
const noPages = <TPage,>(): UseInfiniteQueryResult<InfiniteData<TPage, number>, Error> => ({
  ...settled,
  data: { pages: [], pageParams: [] },
  refetch: vi.fn(),
  fetchNextPage: vi.fn(),
  fetchPreviousPage: vi.fn(),
  hasNextPage: false,
  hasPreviousPage: false,
  isFetchNextPageError: false,
  isFetchingNextPage: false,
  isFetchPreviousPageError: false,
  isFetchingPreviousPage: false,
});

/** The open cases a grant may name, and whether a request must. */
let grantCases: GrantCaseList = { items: [], required: false };
/** What the server finds past the first page, by what was typed. */
let searchedCases: Record<string, GrantCaseList> = {};

/** The approver's pending queue, as a test sets it. */
let pendingQueue: UseInfiniteQueryResult<InfiniteData<unknown, number>, Error> = noPages();

/** A mutation nobody has fired yet. */
const idle = <TData, TVariables>(
  mutate: UseMutationResult<TData, Error, TVariables>["mutate"] = vi.fn<
    (...args: unknown[]) => void
  >()
): UseMutationResult<TData, Error, TVariables> => ({
  data: undefined,
  variables: undefined,
  error: null,
  context: undefined,
  failureCount: 0,
  failureReason: null,
  isError: false,
  isIdle: true,
  isPending: false,
  isPaused: false,
  isSuccess: false,
  status: "idle",
  submittedAt: 0,
  mutate,
  mutateAsync: vi.fn<(...args: unknown[]) => Promise<TData>>(),
  reset: vi.fn(),
});

// Partial: the page also reaches for the page-flattening helper.
vi.mock(import("@/hooks/useAccessGrants"), async (importOriginal) => ({
  ...(await importOriginal()),
  useMyAccessGrants: () => noPages(),
  useAccessGrantQueue: ((status?: string) =>
    status === "pending" ? pendingQueue : noPages()) as never,
  useAccessGrantLimits: () => answered({ max_duration_minutes: requestCeiling }),
  useGrantCases: (options?: { search?: string }) =>
    answered(
      options?.search
        ? (searchedCases[options.search] ?? { items: [], required: false })
        : grantCases
    ),
  useCreateAccessRequest: () => idle(createRequest),
  useCancelAccessRequest: () => idle(),
  useBreakGlass: () => idle(breakGlass),
  useBreakGlassRequirements: () =>
    answered({
      second_factor_required: false,
      max_duration_minutes: 240,
      totp_enrolled: true,
      passkey_enrolled: false,
    }),
  useApproveAccessGrant: () => idle(),
  useDenyAccessGrant: () => idle(),
  useRevokeAccessGrant: () => idle(),
}));

vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () => ({
    communities: [],
    activeCommunity: null,
    activeCommunityId: null,
    activeCommunityReadOnly: false,
    loading: false,
    error: null,
    refreshCommunities: vi.fn(),
    switchCommunity: vi.fn(),
    syncCommunityFromUrl: vi.fn(),
    createCommunity: vi.fn(),
    updateCommunityInState: vi.fn(),
    reorderCommunities: vi.fn(),
    canCreateCommunities: false,
  }),
}));

// The communities the picker finds, and what it last searched for. Only the
// fields the picker reads.
const pickable = [
  { id: 7, name: "Riverside", status: "active" },
  { id: 9, name: "Gone Community", status: "deleted" },
] as PlatformCommunityStorageRead[];
let searched: string | undefined;

vi.mock(import("@/hooks/useSettings"), async (importOriginal) => ({
  ...(await importOriginal()),
  usePlatformCommunities: ((params: { search?: string }) => {
    searched = params.search;
    return answered({ ...buildPage(pickable), support_bound: false });
  }) as unknown as typeof import("@/hooks/useSettings").usePlatformCommunities,
}));

import { SettingsAccessGrantsPage } from "./SettingsAccessGrantsPage";

const render = (
  capabilities: string[] = ["access.request", "access.request_any"],
  routerSearch?: Record<string, unknown>
) =>
  renderPage(SettingsAccessGrantsPage, {
    auth: { user: buildUser({ capabilities: capabilities as never }) },
    routerSearch,
  });

/** Choose a community in the form's picker (the first, or the one given). */
const pickCommunity = async (
  user: ReturnType<typeof userEvent.setup>,
  name: RegExp = /Riverside/,
  picker = 0
) => {
  await user.click((await screen.findAllByRole("combobox", { name: "Community" }))[picker]);
  await user.click(await screen.findByRole("option", { name }));
};

describe("SettingsAccessGrantsPage", () => {
  beforeEach(() => {
    createRequest.mockClear();
    breakGlass.mockClear();
    requestCeiling = 240;
    searched = undefined;
    pendingQueue = noPages();
    grantCases = { items: [], required: false };
  });

  it("names whoever asked by their handle, never their address", async () => {
    const now = new Date().toISOString();
    pendingQueue = {
      ...noPages(),
      data: {
        pageParams: [1],
        pages: [
          {
            items: [
              {
                id: 3,
                user_id: 12,
                user: { id: 12, username: "riverwatch", discriminator: 42, status: "active" },
                community_id: 7,
                community_name: "Riverside",
                purpose: "content",
                access_level: "read",
                status: "pending",
                reason: "looking into a report",
                requested_duration_minutes: 60,
                requested_by_id: 12,
                requested_at: now,
                is_live: false,
              },
            ],
            total_count: 1,
            page: 1,
            page_size: 25,
            has_next: false,
          },
        ],
      },
    } as never;
    render(["access.approve"]);

    expect(await screen.findByText("riverwatch")).toBeInTheDocument();
    expect(screen.getByText("#0042")).toBeInTheDocument();
    expect(screen.queryByText(/@/)).toBeNull();
  });

  it("asks for a content read and no settings by default", async () => {
    const user = userEvent.setup();
    render();

    await pickCommunity(user);
    await user.type(screen.getByLabelText(/reason/i), "looking into a report");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest).toHaveBeenCalledTimes(1);
    expect(createRequest.mock.calls[0][0]).toMatchObject({
      community_id: 7,
      access_level: "read",
      requested_duration_minutes: 240,
    });
    expect(createRequest.mock.calls[0][0].settings_level).toBeUndefined();
  });

  it("offers moderation access only to those who moderate", async () => {
    const user = userEvent.setup();
    const { unmount } = render();
    await user.click(await screen.findByLabelText(/^content access$/i));
    expect(screen.queryByRole("option", { name: "Moderate" })).toBeNull();
    unmount();

    render(["access.request", "access.request_any", "content.moderate"]);
    await pickCommunity(user);
    await user.click(screen.getByLabelText(/^content access$/i));
    await user.click(await screen.findByRole("option", { name: "Moderate" }));
    await user.type(screen.getByLabelText(/reason/i), "a held comment");
    await user.click(screen.getByRole("button", { name: /request access/i }));
    expect(createRequest.mock.calls[0][0]).toMatchObject({ access_level: "moderate" });
  });

  it("offers a moderator moderation access alone", async () => {
    const user = userEvent.setup();
    render(["access.request", "content.moderate"]);
    await pickCommunity(user);
    expect(screen.queryByLabelText(/^settings access$/i)).toBeNull();
    await user.click(screen.getByLabelText(/^content access$/i));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Moderate"]);
    await user.keyboard("{Escape}");
    await user.type(screen.getByLabelText(/reason/i), "a held comment");
    await user.click(screen.getByRole("button", { name: /request access/i }));
    expect(createRequest.mock.calls[0][0]).toMatchObject({ access_level: "moderate" });
    expect(createRequest.mock.calls[0][0].settings_level).toBeUndefined();
  });

  it("offers the windows up to the ceiling the server reports", async () => {
    requestCeiling = 480;
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/duration/i));

    expect(await screen.findByRole("option", { name: /^8 hours$/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^24 hours$/i })).not.toBeInTheDocument();
  });

  it("offers a ceiling the deployment set between the presets", async () => {
    requestCeiling = 120;
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/duration/i));
    await user.click(await screen.findByRole("option", { name: /^2 hours$/i }));
    expect(screen.queryByRole("option", { name: /^4 hours$/i })).not.toBeInTheDocument();

    await pickCommunity(user);
    await user.type(screen.getByLabelText(/reason/i), "a short look");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({ requested_duration_minutes: 120 });
  });

  it("asks for both where the errand needs both", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /read & write/i }));
    await user.click(screen.getByLabelText(/settings access/i));
    await user.click(await screen.findByRole("option", { name: /^superadmin$/i }));

    await pickCommunity(user);
    await user.type(screen.getByLabelText(/reason/i), "clearing up an incident");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({
      access_level: "read_write",
      settings_level: "superadmin",
    });
  });

  it("can ask for settings alone", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /^none$/i }));
    await user.click(screen.getByLabelText(/settings access/i));
    await user.click(await screen.findByRole("option", { name: /^admin$/i }));

    await pickCommunity(user);
    await user.type(screen.getByLabelText(/reason/i), "billing question");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({ settings_level: "admin" });
    expect(createRequest.mock.calls[0][0].access_level).toBeUndefined();
  });

  it("will not send a request that asks for nothing", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /^none$/i }));

    await pickCommunity(user);
    await user.type(screen.getByLabelText(/reason/i), "nothing in particular");

    expect(screen.getByRole("button", { name: /request access/i })).toBeDisabled();
    expect(
      screen.getByText(/choose content access, settings access, or both/i)
    ).toBeInTheDocument();
    expect(createRequest).not.toHaveBeenCalled();
  });

  it("names each community with its id, and says when one is not active", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("combobox", { name: "Community" }));

    expect(await screen.findByRole("option", { name: /Riverside.*#7/ })).toBeInTheDocument();
    // Still pickable: a grant may be needed on exactly this one.
    const gone = screen.getByRole("option", { name: /Gone Community.*Deleted · #9/ });
    expect(gone).not.toHaveAttribute("aria-disabled", "true");
  });

  it("searches the server with what is typed", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("combobox", { name: "Community" }));
    await user.type(screen.getByPlaceholderText("Search by name or number…"), "river");

    await waitFor(() => expect(searched).toBe("river"));
  });

  it("will not send a request before a community is chosen", async () => {
    const user = userEvent.setup();
    render();

    await user.type(await screen.findByLabelText(/reason/i), "looking into a report");

    expect(screen.getByRole("button", { name: /request access/i })).toBeDisabled();
  });

  it("starts with the community it was opened for", async () => {
    const user = userEvent.setup();
    render(["access.request"], { community: 9, name: "Gone Community", form: "request" });

    expect(await screen.findByRole("combobox", { name: "Community" })).toHaveTextContent(
      "Gone Community (#9)"
    );
    await user.type(screen.getByLabelText(/reason/i), "a report about it");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({ community_id: 9 });
  });

  it.each([
    [["access.request", "access.request_any", "content.moderate"], "moderate"],
    [["access.request", "access.request_any"], "read"],
  ])(
    "starts on the level it was opened for, where the reader may ask for it (%s)",
    async (capabilities, sent) => {
      const user = userEvent.setup();
      render(capabilities, {
        community: 9,
        name: "Gone Community",
        form: "request",
        level: "moderate",
      });

      await screen.findByRole("combobox", { name: "Community" });
      await user.type(screen.getByLabelText(/reason/i), "a held comment");
      await user.click(screen.getByRole("button", { name: /request access/i }));
      expect(createRequest.mock.calls[0][0]).toMatchObject({ access_level: sent });
    }
  );

  it("starts breaking glass with the community it was opened for, and only that form", async () => {
    const user = userEvent.setup();
    render(["access.request", "data.bypass"], {
      community: 7,
      name: "Riverside",
      form: "break_glass",
    });

    const [breakGlassPicker, requestPicker] = await screen.findAllByRole("combobox", {
      name: "Community",
    });
    expect(breakGlassPicker).toHaveTextContent("Riverside (#7)");
    expect(requestPicker).not.toHaveTextContent("Riverside");

    await user.type(screen.getAllByLabelText(/reason/i)[0], "incident 12");
    await user.click(screen.getByRole("button", { name: /^break glass$/i }));

    expect(breakGlass.mock.calls[0][0]).toMatchObject({ community_id: 7 });
    expect(breakGlass.mock.calls[0][0].case_task_id).toBeUndefined();
  });

  describe("the case a grant is for", () => {
    const spamWave = {
      task_id: 31,
      title: "Spam wave",
      stream: "moderation",
      subject_community_id: 7,
      mine: true,
      community_notice: "optional",
    } as const;
    const lostPhone = {
      task_id: 32,
      title: "Lost phone",
      stream: "support",
      subject_community_id: null,
      mine: false,
      community_notice: "always",
    } as const;

    /** Choose a case in the form's picker (the first, or the one given). */
    const pickCase = async (user: ReturnType<typeof userEvent.setup>, name: RegExp, picker = 0) => {
      await user.click((await screen.findAllByRole("combobox", { name: "Case" }))[picker]);
      await user.click(await screen.findByRole("option", { name }));
    };

    it("finds a case past the first page on the server", async () => {
      const older = {
        ...lostPhone,
        task_id: 9,
        title: "An old case",
        mine: false,
        subject_community_id: 7,
      };
      grantCases = { items: [spamWave], required: false };
      searchedCases = { "old case": { items: [older], required: false } };
      const user = userEvent.setup();
      render();

      await user.click(await screen.findByRole("combobox", { name: "Case" }));
      await user.type(screen.getByPlaceholderText(/search/i), "old case");
      await user.click(await screen.findByRole("option", { name: /#9 · An old case/ }));
      await user.type(screen.getByLabelText(/reason/i), "looking into a report");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      // Its community comes with it, as one from the first page's would.
      expect(createRequest.mock.calls[0][0]).toMatchObject({
        case_task_id: 9,
        community_id: older.subject_community_id,
      });
      searchedCases = {};
    });

    it("names each case by number and title, its stream, and whether it is yours", async () => {
      grantCases = { items: [spamWave, lostPhone], required: false };
      const user = userEvent.setup();
      render();

      await user.click(await screen.findByRole("combobox", { name: "Case" }));

      expect(
        await screen.findByRole("option", { name: /#31 · Spam wave.*Moderation · yours/ })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("option", { name: /#32 · Lost phone.*Support/ })
      ).not.toHaveTextContent("yours");
    });

    it("will not send a request without a case where one is required, and sends the one chosen", async () => {
      grantCases = { items: [spamWave, lostPhone], required: true };
      const user = userEvent.setup();
      render();

      await pickCommunity(user);
      await user.type(screen.getByLabelText(/reason/i), "looking into a report");

      expect(screen.getByRole("button", { name: /request access/i })).toBeDisabled();
      expect(screen.getByText("Choose the case this access is for.")).toBeInTheDocument();

      await pickCase(user, /Lost phone/);
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0]).toMatchObject({ community_id: 7, case_task_id: 32 });
    });

    it("says when a case is required and there is none to name", async () => {
      grantCases = { items: [], required: true };
      render();

      expect(await screen.findByText(/no open case you can name/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /request access/i })).toBeDisabled();
    });

    it("sends no case where none is required and none was chosen", async () => {
      grantCases = { items: [spamWave], required: false };
      const user = userEvent.setup();
      render();

      await pickCommunity(user);
      await user.type(screen.getByLabelText(/reason/i), "a short look");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0].case_task_id).toBeUndefined();
    });

    it("starts with the case it was opened for, and the community that case is about", async () => {
      grantCases = { items: [lostPhone, spamWave], required: true };
      const user = userEvent.setup();
      render(["access.request"], { case: 31, form: "request" });

      expect(await screen.findByRole("combobox", { name: "Case" })).toHaveTextContent(
        "#31 · Spam wave"
      );
      expect(screen.getByRole("combobox", { name: "Community" })).toHaveTextContent("#7");

      await user.type(screen.getByLabelText(/reason/i), "the spam wave");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0]).toMatchObject({ community_id: 7, case_task_id: 31 });
    });

    it("takes the community the case is about until another is picked", async () => {
      grantCases = { items: [spamWave], required: false };
      const user = userEvent.setup();
      render();

      await pickCase(user, /Spam wave/);
      expect(screen.getByRole("combobox", { name: "Community" })).toHaveTextContent("#7");
      expect(screen.queryByText(/This case is about community/)).toBeNull();
    });

    it("warns, without refusing, when the community picked is not the case's", async () => {
      grantCases = { items: [spamWave], required: true };
      const user = userEvent.setup();
      render();

      await pickCase(user, /Spam wave/);
      await pickCommunity(user, /Gone Community/);

      expect(
        screen.getByText("This case is about community #7, not the one chosen.")
      ).toBeInTheDocument();
      await user.type(screen.getByLabelText(/reason/i), "the spam wave");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0]).toMatchObject({ community_id: 9, case_task_id: 31 });
    });

    it("lets a moderation case tell its community, once access has ended", async () => {
      grantCases = { items: [spamWave, lostPhone], required: true };
      const user = userEvent.setup();
      render();

      expect(screen.queryByRole("combobox", { name: "Tell the community" })).toBeNull();
      await pickCase(user, /Spam wave/);
      await user.click(screen.getByRole("combobox", { name: "Tell the community" }));
      await user.click(await screen.findByRole("option", { name: "Once access has ended" }));
      await user.type(screen.getByLabelText(/reason/i), "the spam wave");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0]).toMatchObject({
        case_task_id: 31,
        community_notice: "when_ended",
      });
    });

    it("offers the choice for a case it was opened for past the first page", async () => {
      grantCases = { items: [lostPhone], required: true };
      searchedCases = { "#9": { items: [{ ...spamWave, task_id: 9 }], required: true } };
      render(["access.request"], { case: 9, form: "request" });

      expect(
        await screen.findByRole("combobox", { name: "Tell the community" })
      ).toBeInTheDocument();
      searchedCases = {};
    });

    it("says a support case always tells its community, and offers no choice", async () => {
      grantCases = { items: [spamWave, lostPhone], required: true };
      const user = userEvent.setup();
      render();

      await pickCommunity(user);
      await pickCase(user, /Lost phone/);
      expect(screen.getByText(/always emailed to the community's superadmins/)).toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: "Tell the community" })).toBeNull();
      await user.type(screen.getByLabelText(/reason/i), "their lost phone");
      await user.click(screen.getByRole("button", { name: /request access/i }));

      expect(createRequest.mock.calls[0][0].community_notice).toBeUndefined();
    });

    it("breaks glass for the case chosen", async () => {
      grantCases = { items: [spamWave, lostPhone], required: true };
      const user = userEvent.setup();
      render(["data.bypass"]);

      expect(await screen.findByText(/Optional\. Without one/)).toBeInTheDocument();
      await pickCase(user, /Lost phone/);
      await pickCommunity(user);
      await user.type(screen.getByLabelText(/reason/i), "incident 12");
      await user.click(screen.getByRole("button", { name: /^break glass$/i }));

      expect(breakGlass.mock.calls[0][0]).toMatchObject({ community_id: 7, case_task_id: 32 });
    });

    it("breaks glass without a case, even where a request needs one", async () => {
      grantCases = { items: [spamWave], required: true };
      const user = userEvent.setup();
      render(["data.bypass"]);

      await pickCommunity(user);
      await user.type(await screen.findByLabelText(/reason/i), "incident 12");
      await user.click(screen.getByRole("button", { name: /^break glass$/i }));

      expect(breakGlass).toHaveBeenCalledTimes(1);
      expect(breakGlass.mock.calls[0][0].case_task_id).toBeUndefined();
    });
  });
});

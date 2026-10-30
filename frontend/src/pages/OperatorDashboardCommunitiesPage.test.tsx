import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useReducer } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildUser } from "@/__tests__/factories";
import { renderPage as renderInRouter } from "@/__tests__/helpers/render";
import type {
  CommunityAction,
  PlatformCommunityStorageRead,
  UserRole,
} from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";

const GIB = 1024 ** 3;

// One mutate spy shared by every row's useUpdateCommunityStorage (the hook is mocked
// to return the same object), so any row's edit resolves to this spy. Storage
// edits and user-limit edits are told apart by the `data` payload they send
// ({ max_storage_bytes } vs { max_users }).
const mutate = vi.fn();
const restore = vi.fn();
const setSuspension = vi.fn();

// What an owner may do to a live community, as the server reports it: every
// control the table and the sheet draw.
const OWNER_ACTIONS: CommunityAction[] = [
  "manage",
  "set_status",
  "billing_support",
  "billing_operator",
  "break_glass",
];

const communitiesData: PlatformCommunityStorageRead[] = [
  {
    id: 7,
    name: "Capped Community",
    member_count: 3,
    tier_name: "Bespoke Plan",
    max_storage_bytes: 10 * GIB,
    max_users: 10,
    max_guests: 10,
    status: "active",
    status_changed_at: null,
    status_choices: ["active", "read_only", "on_hold", "suspended"],
    purge_at: null,
    has_seat: true,
    auth_options: ["providers", "restrictions"],
    banner_image_enabled: true,
    support_enabled: false,
    ai_connections_open: true,
    plugins_open: true,
    lifts_to: null,
    allowed_actions: OWNER_ACTIONS,
  },
  {
    id: 8,
    name: "Open Community",
    member_count: 0,
    tier_name: null,
    max_storage_bytes: null,
    max_users: null,
    max_guests: null,
    status: "active",
    status_changed_at: null,
    status_choices: ["active", "read_only", "on_hold", "suspended"],
    purge_at: null,
    has_seat: true,
    auth_options: ["providers"],
    banner_image_enabled: true,
    support_enabled: true,
    ai_connections_open: true,
    plugins_open: true,
    lifts_to: null,
    allowed_actions: OWNER_ACTIONS,
  },
  {
    id: 9,
    name: "Full Community",
    member_count: 12,
    tier_name: "Bespoke Plan",
    max_storage_bytes: null,
    max_users: 10,
    max_guests: 10,
    status: "suspended",
    status_changed_at: "2026-07-05T00:00:00Z",
    status_choices: ["active", "read_only", "on_hold", "suspended"],
    purge_at: null,
    has_seat: true,
    auth_options: [],
    banner_image_enabled: false,
    support_enabled: false,
    ai_connections_open: true,
    plugins_open: true,
    lifts_to: "active",
    allowed_actions: OWNER_ACTIONS,
  },
  {
    id: 10,
    name: "Gone Community",
    member_count: 4,
    tier_name: null,
    max_storage_bytes: null,
    max_users: null,
    max_guests: null,
    status: "deleted",
    status_changed_at: "2026-09-01T00:00:00Z",
    status_choices: [],
    purge_at: "2026-11-30T00:00:00Z",
    has_seat: true,
    auth_options: [],
    banner_image_enabled: true,
    support_enabled: false,
    ai_connections_open: true,
    plugins_open: true,
    lifts_to: null,
    // Deleted is not a status anybody sets, so the row offers no control for it.
    allowed_actions: OWNER_ACTIONS.filter((action) => action !== "set_status"),
  },
];

// The rows the mocked list serves. Each test starts from the owner's view.
let served: PlatformCommunityStorageRead[] = communitiesData;

// The billing column only renders when a portal is configured; flip this to
// exercise the self-hosted case (no portal, no column).
let billingConfig: {
  url: string;
  operator_handoff: boolean;
  manages_plans?: boolean;
} | null = {
  url: "https://billing.example.com",
  operator_handoff: true,
};

const mintHandoff = vi.fn();

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: billingConfig }),
}));

// What each community says its own arrivals look like, and whether anybody
// outside it has agreed.
let narrowings: {
  connection_id: number;
  community_id: number;
  community_name: string;
  provider_display_name: string;
  claim: string;
  claim_values: string[];
  auto_join: boolean;
  agreed: boolean;
}[] = [];
const agreeNarrowing = vi.fn();

// Where each community stands with the plug-ins that say, as its Usage tab
// shows it, by community.
let pluginSummaries: Record<number, unknown[]> = {};
let pluginSummariesFail = false;

vi.mock("@/api/generated/settings/settings", () => ({
  createPlatformCommunityBillingServiceHandoff: (communityId: number, answer: unknown) =>
    answer ? mintHandoff(communityId, answer) : mintHandoff(communityId),
  useListCommunityPluginSummaries: (communityId: number) =>
    pluginSummariesFail
      ? { data: undefined, isError: true }
      : { data: { items: pluginSummaries[communityId] ?? [] }, isError: false },
  useReadCommunityPluginSummary: () => ({
    data: { values: { used: 250, allowed: 500 }, rows: [] },
    isError: false,
  }),
}));

// Every page drawing the list, so a test can draw them again with what the
// list now holds — as a refetch would.
const listReaders = new Set<() => void>();
const refetchList = () =>
  act(() => {
    for (const redraw of listReaders) redraw();
  });

vi.mock("@/hooks/useSettings", () => ({
  usePlatformCommunities: () => {
    const [, redraw] = useReducer((n: number) => n + 1, 0);
    useEffect(() => {
      listReaders.add(redraw);
      return () => {
        listReaders.delete(redraw);
      };
    }, []);
    return {
      data: { ...buildPage(served), support_bound: supportBound },
      isLoading: false,
      isError: false,
    };
  },
  useUpdateCommunityStorage: () => ({ mutate, isPending: false }),
  useRestoreCommunity: () => ({ mutate: restore, isPending: false }),
  useSetCommunitySuspension: () => ({ mutate: setSuspension, isPending: false }),
  useCommunityNarrowings: () => ({ data: narrowings, isLoading: false }),
  useAgreeCommunityNarrowing: () => ({ mutate: agreeNarrowing, isPending: false }),
}));

vi.mock("@/hooks/useAccessGrants", () => ({
  useBreakGlassRequirements: () => ({
    data: { second_factor_required: true, totp_enrolled: true, passkey_enrolled: false },
  }),
}));

vi.mock("@/hooks/useOperatorUsers", () => ({
  usePlatformUsers: () => ({ data: buildPage([]), isLoading: false }),
}));

// Whether the deployment has somewhere to send help requests, served with the
// list. The help-request entitlement reads it: a community can only be offered
// the form where there is somewhere to send what is written in it.
let supportBound = true;

import { OperatorDashboardCommunitiesPage } from "./OperatorDashboardCommunitiesPage";

const renderPage = (role: UserRole = "owner") =>
  renderInRouter(OperatorDashboardCommunitiesPage, {
    auth: { user: buildUser({ role }) },
  });

/** Render the page, ready to be clicked. */
const mounted = (role: UserRole = "owner") => {
  const user = userEvent.setup();
  renderPage(role);
  return user;
};

/** Render and open one community's operator settings, which is where
 *  everything editable lives. */
const openSheet = async (communityName: string) => {
  const user = mounted();
  expect(await screen.findByText(communityName)).toBeInTheDocument();
  await user.click(screen.getByLabelText(`Manage settings for ${communityName}`));
  return user;
};

const storageInput = () => screen.getByLabelText("Storage limit") as HTMLInputElement;
const userLimitInput = () => screen.getByLabelText("Members") as HTMLInputElement;
const guestLimitInput = () => screen.getByLabelText("Guests") as HTMLInputElement;

/** Type into a box and leave it, which is the only way either cap is saved. */
const typeAndLeave = (input: HTMLInputElement, value: string) => {
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
};

describe("OperatorDashboardCommunitiesPage", () => {
  beforeEach(() => {
    mutate.mockClear();
    restore.mockClear();
    setSuspension.mockClear();
    served = communitiesData;
    mintHandoff.mockReset();
    billingConfig = { url: "https://billing.example.com", operator_handoff: true };
    supportBound = true;
    pluginSummaries = {};
    pluginSummariesFail = false;
    narrowings = [];
  });

  describe("the table", () => {
    it("summarises each community without editing anything", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument(); // id column
      expect(screen.getByText("3 / 10")).toBeInTheDocument(); // members over cap
      expect(screen.getByText("10 GB")).toBeInTheDocument(); // storage cap
      // The community with no caps says so rather than showing a blank.
      expect(screen.getAllByText("No limit").length).toBeGreaterThan(0);
      // Nothing in the table is an editor any more.
      expect(screen.queryByLabelText("Storage limit")).toBeNull();
    });
  });

  // Every cap is the same editor: pre-filled from what is stored, saved on
  // blur, blank meaning no limit at all, and anything the field cannot mean
  // snapped back rather than sent. Capped Community holds every cap at 10;
  // Open Community holds none.
  describe.each([
    {
      what: "storage limit",
      input: storageInput,
      stored: "10",
      typed: "5",
      saves: { max_storage_bytes: 5 * GIB },
      cleared: { max_storage_bytes: null },
      rejects: [["a negative number", "-3"]],
    },
    {
      what: "member limit",
      input: userLimitInput,
      stored: "10",
      typed: "25",
      saves: { max_users: 25 },
      cleared: { max_users: null },
      rejects: [
        ["zero", "0"],
        ["a negative number", "-2"],
        ["a fraction", "2.5"],
      ],
    },
    {
      what: "guest limit",
      input: guestLimitInput,
      stored: "10",
      // 0 is a setting of its own: no new guests.
      typed: "0",
      saves: { max_guests: 0 },
      cleared: { max_guests: null },
      rejects: [
        ["a negative number", "-2"],
        ["a fraction", "2.5"],
      ],
    },
  ])("$what", ({ input, stored, typed, saves, cleared, rejects }) => {
    it("pre-fills the cap that is stored", async () => {
      await openSheet("Capped Community");

      expect(input().value).toBe(stored);
    });

    it("auto-saves a new cap on blur, converting it to what the API stores", async () => {
      await openSheet("Open Community");

      expect(input().value).toBe(""); // blank meaning unlimited
      typeAndLeave(input(), typed);

      expect(mutate).toHaveBeenCalledWith({ communityId: 8, data: saves }, expect.anything());
    });

    it("does not save when the value is left unchanged", async () => {
      await openSheet("Capped Community");

      fireEvent.blur(input());

      expect(mutate).not.toHaveBeenCalled();
    });

    it("saves clearing the cap as no limit at all", async () => {
      await openSheet("Capped Community");

      typeAndLeave(input(), "");

      expect(mutate).toHaveBeenCalledWith({ communityId: 7, data: cleared }, expect.anything());
    });

    it.each(rejects)("reverts %s without saving", async (_label, value) => {
      await openSheet("Capped Community");

      typeAndLeave(input(), value);

      expect(mutate).not.toHaveBeenCalled();
      expect(input().value).toBe(stored); // back to the persisted cap
    });
  });

  describe("lifecycle status", () => {
    const statusControl = (communityName: string) =>
      screen.getByLabelText(`Status for ${communityName}`);

    it("shows each community's current status", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(statusControl("Capped Community")).toHaveTextContent("Active");
      expect(statusControl("Full Community")).toHaveTextContent("Suspended");
    });

    it("applies a non-suspend change immediately (no confirm)", async () => {
      const user = mounted();
      await screen.findByText("Capped Community");

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "Read-only" }));

      expect(mutate).toHaveBeenCalledWith({ communityId: 7, data: { status: "read_only" } });
    });

    it("gates suspend behind a confirm dialog", async () => {
      const user = mounted();
      await screen.findByText("Capped Community");

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "Suspended" }));

      // Not applied yet — the confirm dialog is shown first.
      expect(mutate).not.toHaveBeenCalled();
      expect(await screen.findByText("Suspend Capped Community?")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Suspend community" }));
      expect(mutate).toHaveBeenCalledWith({ communityId: 7, data: { status: "suspended" } });
    });

    it("gates a hold behind its own confirm dialog", async () => {
      const user = mounted();
      await screen.findByText("Capped Community");

      await user.click(statusControl("Capped Community"));
      await user.click(await screen.findByRole("option", { name: "On hold" }));

      expect(mutate).not.toHaveBeenCalled();
      expect(await screen.findByText("Put Capped Community on hold?")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Put on hold" }));
      expect(mutate).toHaveBeenCalledWith({ communityId: 7, data: { status: "on_hold" } });
    });
  });

  describe("a refused save", () => {
    it("puts the stored value back rather than leaving the rejected one", async () => {
      await openSheet("Capped Community");
      const input = storageInput();
      expect(input.value).toBe("10");

      typeAndLeave(input, "99");
      expect(mutate).toHaveBeenCalled();
      // The other cap, typed in while the save was out, is not what was refused.
      fireEvent.change(userLimitInput(), { target: { value: "42" } });

      act(() => mutate.mock.calls[0][1].onError(new Error("nope")));
      expect(storageInput().value).toBe("10");
      expect(userLimitInput().value).toBe("42");
    });

    it("shows what a save actually stored, not what was typed", async () => {
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByLabelText("Manage settings for Capped Community"));
      typeAndLeave(storageInput(), "5.0");

      // The save lands, and the refetched list carries what was stored.
      const capped = communitiesData[0];
      communitiesData[0] = { ...capped, max_storage_bytes: 5 * GIB };
      try {
        act(() => mutate.mock.calls[0][1].onSuccess());
        refetchList();
        expect(storageInput().value).toBe("5");
      } finally {
        communitiesData[0] = capped;
      }
    });
  });

  describe("per-community sign-in grants", () => {
    const grant = (name: string) => screen.getByLabelText(name);
    const SIGN_IN = "Its own sign-in";
    const STANDARD = "Its own security standard";

    // Neither grant waits on the other, so a community holds either, both or
    // none — and both are offered either way.
    it.each([
      ["a community that signs its own people in", "Open Community", true, false],
      ["a community holding neither", "Full Community", false, false],
      ["a community holding both", "Capped Community", true, true],
    ])("shows which grants %s holds", async (_label, communityName, signIn, standard) => {
      await openSheet(communityName);

      expect(grant(SIGN_IN)).toBeEnabled();
      expect(grant(STANDARD)).toBeEnabled();
      if (signIn) expect(grant(SIGN_IN)).toBeChecked();
      else expect(grant(SIGN_IN)).not.toBeChecked();
      if (standard) expect(grant(STANDARD)).toBeChecked();
      else expect(grant(STANDARD)).not.toBeChecked();
    });

    // A click sends the whole set the community would then hold, so adding one
    // keeps the other and withdrawing one leaves the other in place.
    it.each([
      [
        "grants sign-in to a community holding neither",
        "Full Community",
        SIGN_IN,
        9,
        ["providers"],
      ],
      ["grants the security standard on its own", "Full Community", STANDARD, 9, ["restrictions"]],
      [
        "adds the security standard to a community that already signs people in",
        "Open Community",
        STANDARD,
        8,
        ["providers", "restrictions"],
      ],
      [
        "withdraws one grant and leaves the other in place",
        "Capped Community",
        STANDARD,
        7,
        ["providers"],
      ],
    ])("%s", async (_label, communityName, name, communityId, auth_options) => {
      const user = await openSheet(communityName);

      await user.click(grant(name));

      expect(mutate).toHaveBeenCalledWith({ communityId, data: { auth_options } });
    });
  });

  describe("feature entitlements", () => {
    // Neither of these had a control at all before; both are the operator's.
    it.each([
      ["the banner entitlement", "Banner artwork", { banner_image_enabled: false }],
      ["the help-request entitlement", "Help requests", { support_enabled: true }],
    ])("sets %s", async (_label, name, data) => {
      const user = await openSheet("Capped Community");

      await user.click(screen.getByLabelText(name));

      expect(mutate).toHaveBeenCalledWith({ communityId: 7, data });
    });

    it("cannot offer help requests where nothing receives them", async () => {
      supportBound = false;
      await openSheet("Capped Community");

      expect(screen.getByLabelText("Help requests")).toBeDisabled();
    });
  });

  describe("what a community counts as its own", () => {
    const claiming = (agreed: boolean) => [
      {
        connection_id: 3,
        community_id: 7,
        community_name: "Capped Community",
        provider_display_name: "Corp SSO",
        claim: "hd",
        claim_values: ["acme.example"],
        auto_join: true,
        agreed,
      },
    ];

    it("says nothing where a community has claimed nothing", async () => {
      await openSheet("Capped Community");

      expect(screen.queryByText(/who it counts as its own/i)).not.toBeInTheDocument();
    });

    it("shows the values and what agreeing would do", async () => {
      narrowings = claiming(false);
      await openSheet("Capped Community");

      expect(screen.getByText(/hd is acme\.example/i)).toBeInTheDocument();
      expect(screen.getByText(/join on sight/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^agree$/i })).toBeEnabled();
    });

    it("agrees that the values are theirs", async () => {
      narrowings = claiming(false);
      const user = await openSheet("Capped Community");

      await user.click(screen.getByRole("button", { name: /^agree$/i }));

      expect(agreeNarrowing).toHaveBeenCalledWith({ connectionId: 3, agreed: true });
    });

    it("offers to withdraw one already agreed", async () => {
      narrowings = claiming(true);
      const user = await openSheet("Capped Community");

      await user.click(screen.getByRole("button", { name: /withdraw/i }));

      expect(agreeNarrowing).toHaveBeenCalledWith({ connectionId: 3, agreed: false });
    });
  });

  describe("plug-in summaries", () => {
    it("shows the automation runs the community's Usage tab shows", async () => {
      const capped = served.find((community) => community.name === "Capped Community");
      pluginSummaries = {
        [capped?.id ?? 0]: [
          {
            plugin_id: 4,
            name: "Automations",
            returns: [
              { key: "used", type: "int", label: { en: "Runs this month" }, of: "allowed" },
              { key: "allowed", type: "int", label: { en: "Monthly allowance" } },
            ],
          },
        ],
      };
      await openSheet("Capped Community");

      expect(screen.getByText("Automations")).toBeInTheDocument();
      expect(screen.getByText("Runs this month")).toBeInTheDocument();
      expect(screen.getByText("250 of 500")).toBeInTheDocument();
      expect(screen.queryByText("Plug-in usage could not be loaded.")).not.toBeInTheDocument();
    });

    it("says the list could not be loaded rather than showing none", async () => {
      pluginSummariesFail = true;
      await openSheet("Capped Community");

      expect(screen.getByText("Plug-in usage could not be loaded.")).toBeInTheDocument();
    });
  });

  describe("billing column", () => {
    it("labels each button with the community's plan, verbatim", async () => {
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.getByLabelText("Open billing for Capped Community")).toHaveTextContent(
        "Bespoke Plan"
      );
      // No plan named by billing -> neutral label, never an invented tier.
      expect(screen.getByLabelText("Open billing for Open Community")).toHaveTextContent("No plan");
    });

    it.each([
      ["no billing portal is configured", null],
      [
        "the operator route into the portal is not wired",
        { url: "https://billing.example.com", operator_handoff: false },
      ],
    ])("is absent when %s", async (_label, billing) => {
      billingConfig = billing;
      renderPage();

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Open billing for Capped Community")).not.toBeInTheDocument();
    });

    it("mints a handoff for that community and opens the portal with it", async () => {
      const location = { href: "" };
      const tab = { opener: {} as unknown, location, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      mintHandoff.mockResolvedValue({ handoff_token: "tok-123", expires_in_seconds: 60 });

      renderPage();
      await userEvent.click(await screen.findByLabelText("Open billing for Capped Community"));

      expect(mintHandoff).toHaveBeenCalledWith(7);
      // The console reads the community off the session it exchanges, so the URL
      // never names one; the token rides in the fragment, which is not sent to
      // the server. The key is `support_handoff` — the console ignores the
      // `handoff` the community-admin flow uses.
      const [path, fragment] = location.href.split("#");
      expect(path).toBe("https://billing.example.com/support?lang=en");
      expect(fragment).toBe("support_handoff=tok-123");
      expect(tab.opener).toBeNull();

      openSpy.mockRestore();
    });

    it("closes the blank tab when minting fails", async () => {
      const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      mintHandoff.mockRejectedValue(new Error("nope"));

      renderPage();
      await userEvent.click(await screen.findByLabelText("Open billing for Capped Community"));

      expect(tab.close).toHaveBeenCalled();
      expect(tab.location.href).toBe("");

      openSpy.mockRestore();
    });
  });

  describe("where billing sets plans", () => {
    beforeEach(() => {
      billingConfig = {
        url: "https://billing.example.com",
        operator_handoff: true,
        manages_plans: true,
      };
    });

    it("shows the plan and does not let it be set", async () => {
      await openSheet("Capped Community");

      expect(userLimitInput()).toBeDisabled();
      expect(storageInput()).toBeDisabled();
      expect(
        screen.getByText("Billing sets this community's limits and features.")
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Change in billing" })).toBeInTheDocument();
    });

    it("opens the operator console to change it", async () => {
      const location = { href: "" };
      const tab = { opener: {} as unknown, location, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      mintHandoff.mockResolvedValue({ handoff_token: "tok-9", expires_in_seconds: 60 });

      const user = await openSheet("Capped Community");
      await user.click(screen.getByRole("button", { name: "Change in billing" }));

      expect(mintHandoff).toHaveBeenCalledWith(7);
      expect(location.href.split("#")[0]).toBe("https://billing.example.com/operator?lang=en");

      openSpy.mockRestore();
    });
  });

  describe("the second factor", () => {
    it("asks for it when the grant is new, then opens billing with the answer", async () => {
      const location = { href: "" };
      const tab = { opener: {} as unknown, location, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      const refusal = Object.assign(new Error("factor"), {
        isAxiosError: true,
        response: { status: 401, data: { detail: "ACCESS_GRANT_SECOND_FACTOR_REQUIRED" } },
      });
      mintHandoff
        .mockRejectedValueOnce(refusal)
        .mockResolvedValueOnce({ handoff_token: "tok-2", expires_in_seconds: 60 });

      const user = mounted();
      await user.click(await screen.findByLabelText("Open billing for Capped Community"));
      expect(tab.close).toHaveBeenCalled();

      await user.type(await screen.findByLabelText("Your authenticator code"), "123 456");
      await user.click(screen.getByRole("button", { name: "Open billing" }));

      expect(mintHandoff).toHaveBeenLastCalledWith(7, { code: "123456" });
      expect(location.href).toContain("support_handoff=tok-2");

      openSpy.mockRestore();
    });
  });

  describe("the status control", () => {
    it("offers the statuses the server says the operator may set", async () => {
      communitiesData[0] = { ...communitiesData[0], status_choices: ["active", "suspended"] };
      try {
        const user = mounted();
        await user.click(await screen.findByLabelText("Status for Capped Community"));

        expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
          "Active",
          "Suspended",
        ]);
      } finally {
        communitiesData[0] = {
          ...communitiesData[0],
          status_choices: ["active", "read_only", "on_hold", "suspended"],
        };
      }
    });
  });

  describe("a deleted community", () => {
    it("shows a tag instead of the status control", async () => {
      renderPage();

      expect(await screen.findByText("Gone Community")).toBeInTheDocument();
      expect(screen.getByText("Deleted")).toBeInTheDocument();
      // No control at all: deleted is not a status you pick, so the row that
      // holds it offers nothing to pick with.
      expect(screen.queryByLabelText("Status for Gone Community")).not.toBeInTheDocument();
      // ...while a live community still has its dropdown.
      expect(screen.getByLabelText("Status for Capped Community")).toBeInTheDocument();
    });

    it("offers a restore with the date everything is destroyed on", async () => {
      await openSheet("Gone Community");

      // The purge date is an instant, not a calendar day, so it is drawn in
      // the reader's own timezone — computed here the same way rather than
      // written out, which would only pass in the timezone it was written in.
      const expected = dateTimeFormat(undefined, { dateStyle: "medium" }).format(
        new Date("2026-11-30T00:00:00Z")
      );
      expect(
        screen.getByText(`Deleted. Everything in it is destroyed on ${expected}.`)
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Restore community" })).toBeInTheDocument();
      // Its caps are shown but frozen — worth seeing while you decide, not
      // worth setting on a community nobody can reach.
      expect(userLimitInput()).toBeDisabled();
      expect(storageInput()).toBeDisabled();
    });

    it("restores it at the status the operator picks", async () => {
      const user = await openSheet("Gone Community");
      await user.click(screen.getByRole("button", { name: "Restore community" }));

      // This community still has somebody to run it, so the seat step is
      // skipped and the only question is what it comes back as.
      expect(screen.getByText("Choose what the community comes back as.")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Restore" }));

      expect(restore).toHaveBeenCalledWith({
        communityId: 10,
        data: { status: "active", seat_user_id: null },
      });
    });
  });

  // Every control is drawn from the row's `allowed_actions`, which the server
  // works out for the reader: nothing here asks the reader's role.
  describe("what each reader may do", () => {
    /** Serve every row with these actions and no status choices, the way the
     *  server serves them to somebody who cannot set a status. */
    const serveWith = (
      actions: CommunityAction[],
      overrides: Partial<PlatformCommunityStorageRead> = {}
    ) => {
      served = communitiesData.map((community) => ({
        ...community,
        status_choices: [],
        allowed_actions: actions,
        ...overrides,
      }));
    };

    it("tells somebody without the list that they need a staff role", async () => {
      renderPage("member");

      expect(
        await screen.findByText("You need a platform staff role to see communities.")
      ).toBeInTheDocument();
      expect(screen.queryByText("Capped Community")).not.toBeInTheDocument();
    });

    it("shows support each status as a tag, and nothing to manage", async () => {
      serveWith(["billing_support", "request_access"]);
      renderPage("support");

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Status for Capped Community")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/^Manage settings for/)).not.toBeInTheDocument();
      expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
      expect(screen.getByText("Suspended")).toBeInTheDocument();
      // Deleted ones are listed for support too.
      expect(screen.getByText("Deleted")).toBeInTheDocument();
      // The support console is theirs to open.
      expect(screen.getByLabelText("Open billing for Capped Community")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Suspend/ })).not.toBeInTheDocument();
    });

    it("offers the status control only where the row allows setting it", async () => {
      served = communitiesData.map((community) =>
        community.id === 7
          ? community
          : {
              ...community,
              status_choices: [],
              allowed_actions: community.allowed_actions.filter(
                (action) => action !== "set_status"
              ),
            }
      );
      renderPage();

      expect(await screen.findByLabelText("Status for Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Status for Open Community")).not.toBeInTheDocument();
    });

    it("leaves the support console out without billing support", async () => {
      serveWith(["request_access"]);
      renderPage("support");

      expect(await screen.findByText("Capped Community")).toBeInTheDocument();
      expect(screen.queryByLabelText("Open billing for Capped Community")).not.toBeInTheDocument();
    });

    it("lets a moderator suspend a community once they confirm", async () => {
      serveWith(["billing_support", "request_access", "suspend"]);
      const user = mounted("moderator");

      await user.click(await screen.findByRole("button", { name: "Suspend Capped Community" }));
      expect(setSuspension).not.toHaveBeenCalled();
      expect(await screen.findByText("Suspend Capped Community?")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Suspend community" }));
      expect(setSuspension).toHaveBeenCalledWith({ communityId: 7, data: { suspended: true } });
    });

    it("says suspending a deleted community stops its countdown", async () => {
      serveWith(["suspend"]);
      const user = mounted("moderator");

      await user.click(await screen.findByRole("button", { name: "Suspend Gone Community" }));

      expect(await screen.findByText(/stops the countdown to its destruction/)).toBeInTheDocument();
    });

    it("says where lifting a suspension returns the community to", async () => {
      serveWith(["lift"], { status: "suspended", lifts_to: "read_only" });
      const user = mounted("moderator");

      await user.click(
        await screen.findByRole("button", { name: "Lift the suspension on Full Community" })
      );

      expect(
        await screen.findByText(/It returns to the status it had before: Read-only\./)
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Lift suspension" }));
      expect(setSuspension).toHaveBeenCalledWith({ communityId: 9, data: { suspended: false } });
    });

    it("warns that one suspended out of deletion goes back to counting down", async () => {
      serveWith(["lift"], { status: "suspended", lifts_to: "deleted" });
      const user = mounted("moderator");

      await user.click(
        await screen.findByRole("button", { name: "Lift the suspension on Gone Community" })
      );

      expect(
        await screen.findByText(/goes back to being deleted, and the countdown/)
      ).toBeInTheDocument();
    });

    it("opens the access request for the row's community", async () => {
      serveWith(["request_access"]);
      const user = mounted("support");

      await user.click(await screen.findByRole("button", { name: "Actions for Capped Community" }));
      const item = await screen.findByRole("menuitem", { name: "Request access" });

      expect(item.getAttribute("href")).toContain("community=7");
      expect(item.getAttribute("href")).toContain("form=request");
      expect(screen.queryByRole("menuitem", { name: "Break glass" })).not.toBeInTheDocument();
    });

    it("starts a moderator's request on Moderate", async () => {
      serveWith(["request_access"]);
      const user = mounted("moderator");

      await user.click(await screen.findByRole("button", { name: "Actions for Capped Community" }));
      const item = await screen.findByRole("menuitem", { name: "Request access" });
      expect(item.getAttribute("href")).toContain("level=moderate");
    });

    it("opens breaking glass for the row's community", async () => {
      const user = mounted();

      await user.click(await screen.findByRole("button", { name: "Actions for Open Community" }));
      const item = await screen.findByRole("menuitem", { name: "Break glass" });

      expect(item.getAttribute("href")).toContain("community=8");
      expect(item.getAttribute("href")).toContain("form=break_glass");
    });
  });
});

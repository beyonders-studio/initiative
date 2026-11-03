/**
 * The platform roster, and the things about it that are not styling.
 *
 * The roster renders the address exactly as the API sent it and never
 * reassembles one — shortening is the server's job, and this page's job is to
 * not undo it. It identifies an account by its handle and nothing else: the
 * name somebody filled in is theirs, and an operator needs none of it to do
 * any of this.
 *
 * The levers themselves live in the sheet behind Manage, where the case an act
 * is for can be named, and each one is drawn only where the row's
 * `allowed_actions` names it — the server works that out per viewer, so
 * nothing here asks for a role. The row's menu only exports.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  GrantCaseRead,
  OperatorAccountCaseRead,
  OperatorUserRead,
  UserAction,
  UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";

// The roster the mocked hook serves. Each test sets it, so no test depends on
// what another left behind.
const state = vi.hoisted(() => ({
  roster: [] as OperatorUserRead[],
  search: undefined as string | null | undefined,
  clearSecondFactor: vi.fn(),
  revokeApiKeys: vi.fn(),
  signOutEverywhere: vi.fn(),
  clearProfileField: vi.fn(),
  cases: [] as OperatorAccountCaseRead[],
  casesEnabled: undefined as boolean | undefined,
  grantCases: [] as GrantCaseRead[],
  signOutCase: undefined as number | null | undefined,
  resetPassword: vi.fn(),
  resetCase: undefined as number | null | undefined,
  deleteCase: undefined as number | null | undefined,
}));

vi.mock("@/hooks/useAccessGrants", () => ({
  useGrantCases: () => ({
    data: { items: state.grantCases, required: false },
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({}),
}));

vi.mock("@/hooks/useOperatorUsers", () => ({
  usePlatformUsers: (params: { search?: string | null }) => {
    state.search = params.search;
    return { data: buildPage(state.roster), isLoading: false, isError: false };
  },
  useOperatorTriggerPasswordReset: (_options: unknown, caseTaskId?: number | null) => {
    state.resetCase = caseTaskId;
    return { mutate: state.resetPassword, isPending: false };
  },
  useOperatorDeleteUser: (_userId: number, _options: unknown, caseTaskId?: number | null) => {
    state.deleteCase = caseTaskId;
    return { mutate: vi.fn(), isPending: false };
  },
  useUserDeletionEligibility: () => ({ data: undefined, refetch: vi.fn(), isFetching: false }),
  useOperatorResendVerification: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorSetUsername: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorClearAgeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorLiftSignInLock: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorClearSecondFactor: () => ({ mutate: state.clearSecondFactor, isPending: false }),
  useOperatorSetSuspension: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorReactivateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRestoreUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorUpdatePlatformRole: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRemoveAvatar: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRevokeApiKeys: () => ({ mutate: state.revokeApiKeys, isPending: false }),
  useOperatorSignOutEverywhere: (_options: unknown, caseTaskId?: number | null) => {
    state.signOutCase = caseTaskId;
    return { mutate: state.signOutEverywhere, isPending: false };
  },
  useOperatorClearProfileField: () => ({ mutate: state.clearProfileField, isPending: false }),
  useOperatorAccountCases: (_userId: number, options?: { enabled?: boolean }) => {
    state.casesEnabled = options?.enabled;
    return { data: state.cases, isLoading: false, isError: false };
  },
  useExportPlatformUsersCsv: () => ({ mutate: vi.fn() }),
}));

import { SettingsPlatformUsersPage } from "./SettingsPlatformUsersPage";

// As the server serves it: addresses already reduced, and what the viewer may
// do to each account worked out — here, nothing to the owner's own row and
// `actions` to the member's.
const masked = (actions: UserAction[] = []) =>
  [
    {
      ...buildUser({ role: "owner" }),
      email: "o***r@e***m",
      username: "owner",
      allowed_actions: [],
      open_case_count: 0,
    },
    {
      ...buildUser({ role: "member" }),
      email: "u***1@e***m",
      username: "member-one",
      allowed_actions: actions,
      open_case_count: 0,
    },
  ] as unknown as OperatorUserRead[];

const renderRoster = (
  roster: OperatorUserRead[],
  viewer: UserRead = buildUser({ role: "owner" })
) => {
  state.roster = roster;
  return renderPage(() => <SettingsPlatformUsersPage />, { auth: { user: viewer } });
};

/** Open the sheet for the account with this handle. */
const openSheet = async (handle = "member-one") => {
  await userEvent.click(
    await screen.findByRole("button", { name: new RegExp(`manage account @?${handle}`, "i") })
  );
  return screen.findByRole("dialog");
};

/** One lever in the sheet, whether it is labelled or captioned. */
const lever = (sheet: HTMLElement, name: string) =>
  within(sheet).queryByLabelText(name) ?? within(sheet).queryByText(name);

describe("SettingsPlatformUsersPage", () => {
  beforeEach(() => {
    state.roster = [];
    state.clearSecondFactor.mockClear();
  });

  it("identifies an account by its handle, and shows no address or name", async () => {
    const rows = masked();
    renderRoster(rows);

    await screen.findByText("owner");
    // Not even the shortened form the server still sends: an operator does
    // not administer an account by its address.
    expect(screen.queryByText("o***r@e***m")).not.toBeInTheDocument();
    expect(screen.queryByText("u***1@e***m")).not.toBeInTheDocument();
    expect(screen.queryByText(/@example\.com/)).not.toBeInTheDocument();
    // A row is identified by handle, which is what the filter box searches.
    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/filter by handle/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Name/ })).not.toBeInTheDocument();
  });

  it("marks an account whose password sign-in is turned off", async () => {
    const rows = masked();
    rows[1].sign_in_locked_until = "2026-09-24T12:00:00Z";
    renderRoster(rows);

    await screen.findByText("owner");
    expect(screen.getAllByText("Password sign-in off")).toHaveLength(1);
    expect(screen.getAllByText(/^Until .*2026/)).toHaveLength(1);
  });

  it("searches the server with a whole handle pasted in", async () => {
    const rows = masked();
    renderRoster(rows);

    const box = await screen.findByPlaceholderText(/filter by handle/i);
    const whole = `owner#${String(rows[0].discriminator).padStart(4, "0")}`;

    // What somebody pastes out of a ticket, sent as it was typed: the server
    // pins the one account that handle names.
    await userEvent.type(box, whole);

    await waitFor(() => expect(state.search).toBe(whole));
  });

  it("offers a sort control on every identifying column, and only those", async () => {
    renderRoster(masked());

    for (const label of [/^User ID/, /^Handle/, /^Status/]) {
      expect(await screen.findByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /^Email/ })).not.toBeInTheDocument();
    // The role is decided in the sheet now, so it is not a column to sort by;
    // neither is the actions column something you can order rows by.
    expect(screen.queryByRole("button", { name: /^Role/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Actions$/ })).not.toBeInTheDocument();
  });

  it("keeps only the export in the row's menu", async () => {
    renderRoster(masked(["delete", "suspend", "reset_password", "clear_second_factor"]));

    const triggers = await screen.findAllByRole("button", { name: /actions for/i });
    expect(triggers).toHaveLength(2);
    await userEvent.click(triggers[1]);

    // Every act on the account is in its sheet, where its case can be named.
    const menu = await screen.findByRole("menu");
    expect(menu).toHaveTextContent("Export");
    expect(menu).not.toHaveTextContent("Delete user");
    expect(menu).not.toHaveTextContent("Reset password");
    expect(menu).not.toHaveTextContent("Clear two-factor authentication");
  });

  it("marks an account with open cases on its row", async () => {
    const rows = masked();
    rows[1].open_case_count = 2;
    renderRoster(rows);

    expect(await screen.findByText("2 open cases")).toBeInTheDocument();
    expect(screen.getAllByText(/open case/)).toHaveLength(1);
  });
});

describe("SettingsPlatformUsersPage manage sheet", () => {
  beforeEach(() => {
    state.roster = [];
  });

  it.each<[string, UserAction[], string[], string[]]>([
    [
      "every lever the row allows",
      ["rename", "remove_avatar", "suspend", "change_role"],
      ["Username", "Profile picture", "Suspended", "Role"],
      [],
    ],
    [
      "nothing the row does not name",
      ["rename", "suspend"],
      ["Username", "Suspended"],
      ["Role", "Profile picture"],
    ],
    [
      "a lifted suspension's switch where it can be lifted",
      ["unsuspend"],
      ["Suspended"],
      ["Username"],
    ],
  ])("offers %s", async (_label, actions, shown, hidden) => {
    const rows = masked(actions);
    rows[1].avatar_url = "/api/v1/users/2/avatar/abc";
    renderRoster(rows);

    const sheet = await openSheet();

    for (const name of shown) expect(lever(sheet, name)).toBeInTheDocument();
    for (const name of hidden) expect(lever(sheet, name)).not.toBeInTheDocument();
  });

  it.each<[string, UserAction[], boolean]>([
    ["revokes the keys that still work where allowed", ["revoke_api_keys"], true],
    ["offers nothing to revoke where the row does not allow it", ["rename"], false],
  ])("%s", async (_label, actions, offered) => {
    state.revokeApiKeys.mockClear();
    const rows = masked(actions);
    rows[1].api_key_count = 2;
    renderRoster(rows, buildUser({ role: "moderator" }));

    const sheet = await openSheet();
    const revoke = within(sheet).queryByRole("button", { name: "Revoke" });
    if (!offered) {
      expect(revoke).not.toBeInTheDocument();
      return;
    }

    // Whatever runs on them stops at once, so it asks first.
    await userEvent.click(revoke as HTMLElement);
    const dialog = await screen.findByRole("alertdialog");
    expect(state.revokeApiKeys).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));
    expect(state.revokeApiKeys).toHaveBeenCalledWith(rows[1].id);
  });

  it("signs an account out everywhere once asked twice", async () => {
    state.signOutEverywhere.mockClear();
    const rows = masked(["sign_out_everywhere"]);
    renderRoster(rows, buildUser({ role: "moderator" }));

    const sheet = await openSheet();
    await userEvent.click(within(sheet).getByRole("button", { name: "Sign out everywhere" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(state.signOutEverywhere).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    expect(state.signOutEverywhere).toHaveBeenCalledWith(rows[1].id);
  });

  it("takes an act for the case chosen in the sheet", async () => {
    state.grantCases = [
      {
        task_id: 41,
        title: "Spam wave",
        stream: "moderation",
        subject_community_id: null,
        mine: true,
        community_notice: "optional",
      },
    ];
    const rows = masked(["sign_out_everywhere"]);
    renderRoster(rows, buildUser({ role: "moderator" }));

    const sheet = await openSheet();
    expect(state.signOutCase).toBeNull();
    await userEvent.click(within(sheet).getByRole("combobox", { name: "For case" }));
    await userEvent.click(await screen.findByRole("option", { name: /#41 · Spam wave/ }));
    expect(state.signOutCase).toBe(41);
    state.grantCases = [];
  });

  it("offers no case to choose where there is none", async () => {
    state.grantCases = [];
    renderRoster(masked(["sign_out_everywhere"]), buildUser({ role: "moderator" }));
    const sheet = await openSheet();
    expect(within(sheet).queryByRole("combobox", { name: "For case" })).toBeNull();
  });

  it.each<[UserAction, string, string]>([
    ["clear_display_names", "Clear their names in communities", "display_names"],
    ["clear_custom_status", "Clear status line", "custom_status"],
    ["clear_decorations", "Clear decorations", "decorations"],
  ])("clears what the row allows (%s), once confirmed", async (action, label, field) => {
    state.clearProfileField.mockClear();
    const rows = masked([action]);
    renderRoster(rows, buildUser({ role: "moderator" }));

    const sheet = await openSheet();
    // Only the one the row names is offered.
    expect(within(sheet).getAllByRole("button", { name: /^Clear/ })).toHaveLength(1);
    await userEvent.click(within(sheet).getByRole("button", { name: label }));
    const dialog = await screen.findByRole("alertdialog");
    expect(state.clearProfileField).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Clear" }));
    expect(state.clearProfileField).toHaveBeenCalledWith({ userId: rows[1].id, field });
  });

  it("offers nothing to open on a row that allows nothing", async () => {
    renderRoster(masked([]), buildUser({ role: "moderator" }));

    await screen.findByText("owner");
    expect(screen.queryByRole("button", { name: /manage account/i })).not.toBeInTheDocument();
  });

  it.each([true, false])(
    "offers a password reset only where the row allows it (%s)",
    async (allowed) => {
      state.resetPassword.mockClear();
      const rows = masked(allowed ? ["reset_password"] : ["rename"]);
      renderRoster(rows, buildUser({ role: "moderator" }));

      const sheet = await openSheet();
      const reset = within(sheet).queryByRole("button", { name: "Reset password" });
      if (!allowed) {
        expect(reset).not.toBeInTheDocument();
        return;
      }
      await userEvent.click(reset as HTMLElement);
      const dialog = await screen.findByRole("alertdialog");
      expect(state.resetPassword).not.toHaveBeenCalled();
      await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
      expect(state.resetPassword).toHaveBeenCalledWith(rows[1].id);
    }
  );

  it.each([true, false])(
    "offers to clear an authenticator only where allowed (%s)",
    async (allowed) => {
      state.clearSecondFactor.mockClear();
      const rows = masked(allowed ? ["clear_second_factor"] : ["rename"]);
      renderRoster(rows, buildUser({ role: "moderator" }));

      const sheet = await openSheet();
      const clear = lever(sheet, "Two-factor authentication");
      if (!allowed) {
        expect(clear).not.toBeInTheDocument();
        return;
      }
      // It signs them out everywhere, so it asks first.
      await userEvent.click(within(sheet).getByRole("button", { name: "Clear" }));
      const dialog = await screen.findByRole("alertdialog");
      expect(state.clearSecondFactor).not.toHaveBeenCalled();
      await userEvent.click(within(dialog).getByRole("button", { name: "Clear it" }));
      expect(state.clearSecondFactor).toHaveBeenCalledWith(rows[1].id);
    }
  );

  it("takes a one-off act and a deletion for the case chosen in the sheet", async () => {
    state.grantCases = [
      {
        task_id: 43,
        title: "Locked out",
        stream: "support",
        subject_community_id: null,
        mine: true,
        community_notice: "always",
      },
    ];
    renderRoster(masked(["reset_password", "delete"]), buildUser({ role: "operator" }));

    const sheet = await openSheet();
    await userEvent.click(within(sheet).getByRole("combobox", { name: "For case" }));
    await userEvent.click(await screen.findByRole("option", { name: /#43 · Locked out/ }));
    expect(state.resetCase).toBe(43);

    await userEvent.click(within(sheet).getByRole("button", { name: "Delete…" }));
    await waitFor(() => expect(state.deleteCase).toBe(43));
    state.grantCases = [];
  });

  it("lists an account's open cases, read once the sheet is open", async () => {
    state.cases = [
      {
        task_id: 55,
        stream: "moderation",
        community_id: 3,
        initiative_id: 4,
        project_id: 5,
        filed: false,
      },
      {
        task_id: 56,
        stream: "support",
        community_id: 3,
        initiative_id: 4,
        project_id: 6,
        filed: true,
      },
    ];
    const rows = masked();
    rows[1].open_case_count = 2;
    // Support can open the sheet for its cases alone.
    renderRoster(rows, buildUser({ role: "support" }));

    const sheet = await openSheet();

    expect(state.casesEnabled).toBe(true);
    expect(
      within(sheet).getByText("2 open cases they filed or that are about them.")
    ).toBeInTheDocument();
    const about = within(sheet).getByRole("link", { name: /Moderation · About them/ });
    expect(about).toHaveAttribute("href", "/c/3/i/4/projects/5/tasks/55");
    expect(about).toHaveTextContent("#55");
    expect(within(sheet).getByRole("link", { name: /Support · Filed by them/ })).toHaveAttribute(
      "href",
      "/c/3/i/4/projects/6/tasks/56"
    );
    expect(
      within(sheet).getByText("Opening a case needs access to the project it is kept in.")
    ).toBeInTheDocument();
    state.cases = [];
  });
});

describe("an account on its way out", () => {
  const deleted = (purgeAt: string | null): OperatorUserRead[] => {
    const rows = masked();
    rows[1] = { ...rows[1], status: "deleted", purge_at: purgeAt };
    return rows;
  };

  it("is tagged, with the day it is erased", async () => {
    renderRoster(deleted("2026-10-20T12:00:00Z"));

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    // An instant, not a calendar day, so it is drawn in the reader's own
    // timezone — computed here the same way rather than written out.
    const expected = dateTimeFormat("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date("2026-10-20T12:00:00Z"));
    expect(screen.getByText(`Erased ${expected}`)).toBeInTheDocument();
  });

  it("says so plainly where the deployment erases nobody", async () => {
    renderRoster(deleted(null));

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    expect(screen.getByText("Kept indefinitely")).toBeInTheDocument();
  });
});

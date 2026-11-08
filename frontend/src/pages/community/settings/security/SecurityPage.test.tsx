import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import type {
  CommunityAuthOption,
  CommunityAuthPolicyRead,
  CommunityAuthSettingsRead,
  CommunityPeopleFigures,
  CommunityRole,
} from "@/api/generated/initiativeAPI.schemas";
import type { CommunityEntry } from "@/hooks/useCommunities";

// What the server says about this community and this member. Flipped per test.
let communityRole: CommunityRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let communityId = 4;
const openPolicy: CommunityAuthPolicyRead = {
  policy: "open",
  provider_id: null,
  provider_slug: null,
  provider_display_name: null,
  require_methods: [],
  factor_required_by_platform: false,
};
/** How many people a rule would reach. Nobody, unless a case says otherwise. */
const figures = (overrides: Partial<CommunityPeopleFigures> = {}): CommunityPeopleFigures => ({
  total: 0,
  without_factor: 0,
  without_passkey: 0,
  never_through_any: 0,
  never_through: [],
  ...overrides,
});
/** Every control on the page, and the deployment's answers beside them.
 *  Undefined while it is still loading. */
let settings: CommunityAuthSettingsRead | undefined;
const baseSettings = (): CommunityAuthSettingsRead => ({
  auth_options: ["restrictions", "providers"],
  auth_policy: openPolicy,
  guest_auth_policy: openPolicy,
  enforce_compliance_session: false,
  require_second_factor: false,
  allow_push_notifications: true,
  allow_email_notifications: true,
  redact_notification_content: false,
  push_allowed_by_platform: true,
  email_allowed_by_platform: true,
  redacted_by_platform: false,
  allow_engagement_ranking: true,
  engagement_ranking_allowed_by_platform: true,
  allow_ai: true,
  ai_offered_by_platform: true,
  guest_max_days: null,
  guest_max_days_by_platform: 90,
  set_by_deployment: [],
  member_figures: figures(),
  guest_figures: figures(),
});
/** Change what the server says, for a case that varies it. */
const stored = (patch: Partial<CommunityAuthSettingsRead>) => {
  settings = { ...(settings ?? baseSettings()), ...patch };
};
const connection = (id: number, providerId: number, slug: string, name: string) => ({
  id,
  provider_id: providerId,
  provider_slug: slug,
  provider_display_name: name,
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  accepts_provider_placement: false,
  login_ready: true,
});
let connections = [
  connection(1, 11, "corp", "Corp SSO"),
  connection(2, 12, "contractors", "Contractors"),
];
/** What the deployment offers this community to connect to. Empty is a state of
 *  its own: nothing to connect means a different answer than nothing connected. */
let connectable: { id: number; slug: string; display_name: string }[] = [
  { id: 11, slug: "corp", display_name: "Corp SSO" },
];

// Every control saves through the same PATCH, one field at a time.
const save = vi.fn();
let secondFactorAvailable = true;
let guestsEnabled = false;
const refreshCommunities = vi.fn(() => Promise.resolve<CommunityEntry[]>([]));

// Partial: the render helper reaches for ``CommunityContext`` from this module.
vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () => {
    const activeCommunity: CommunityEntry = {
      ...buildCommunity({ id: communityId, name: "Test Community", role: communityRole }),
      grantSettingsLevel,
    };
    return {
      communities: [activeCommunity],
      activeCommunity,
      activeCommunityId: communityId,
      activeCommunityReadOnly: false,
      loading: false,
      error: null,
      refreshCommunities,
      switchCommunity: vi.fn(),
      syncCommunityFromUrl: vi.fn(),
      createCommunity: vi.fn(),
      updateCommunityInState: vi.fn(),
      reorderCommunities: vi.fn(),
      canCreateCommunities: false,
    };
  },
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => communityId }));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ secondFactorAvailable, guestsEnabled }),
}));

// ``useServer`` is left real: the render helper provides its context, and
// mocking the module would take ``ServerContext`` with it.

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useCommunityAuthSettings: () => ({ data: settings }),
  useUpdateCommunityAuthSettings: () => ({ mutate: save, isPending: false }),
  useCommunityProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectableProviders: () => ({ data: connectable, isLoading: false }),
  useCommunityLoginProviders: () => ({ data: { providers: [] } }),
  useConnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateProviderConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useDisconnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
  useCommunityClaimRules: () => ({
    data: {
      rules: [],
      reporting_provider_ids: [],
      provider_rules: [],
      placement_everywhere: false,
    },
    isLoading: false,
  }),
  useCreateClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useCustomRoleClaimRules: () => ({ data: [], isLoading: false }),
  useCreateCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useOrderCustomRoleClaimRules: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { SecurityPage } from "./SecurityPage";

const render = () => renderWithProviders(<SecurityPage />, { auth: { user: buildUser() } });

const requirementRadio = () => screen.getByLabelText(/through our providers/i);

/** Render the page, ready to be clicked. */
const mounted = () => {
  const user = userEvent.setup();
  render();
  return user;
};

/** Open the dialog a Sign-in rules row changes in. */
const change = (user: ReturnType<typeof userEvent.setup>, rule: string) =>
  user.click(screen.getByRole("button", { name: `Change ${rule}` }));

/** The save's refusal, as the server names what is missing. */
const refuse = (unmet?: string, detail = "AUTH_RULE_SELF_UNSATISFIED") => {
  // Lower-cased, as axios hands a response's headers back.
  const headers = new AxiosHeaders(unmet ? { "x-auth-policy-unmet": unmet } : {});
  const error = new AxiosError("refused", "ERR_BAD_REQUEST");
  error.response = {
    status: 400,
    statusText: "",
    data: { detail },
    headers,
    config: { headers: new AxiosHeaders() },
  };
  const sent = save.mock.calls[0][1] as { onError: (err: unknown) => void };
  act(() => sent.onError(error));
};

/** A rule already saved on the community, with only what a case varies named. */
const savedPolicy = (overrides: Partial<CommunityAuthPolicyRead>) => {
  stored({ auth_policy: { ...openPolicy, policy: "required", ...overrides } });
};

/** The provider picker lists the same names the registry below does, so
 * choose from the open listbox rather than from the page. */
const chooseOption = async (user: ReturnType<typeof userEvent.setup>, name: string | RegExp) => {
  await user.click(await screen.findByRole("combobox"));
  await user.click(await screen.findByRole("option", { name }));
};

describe("SecurityPage", () => {
  beforeEach(() => {
    save.mockClear();
    refreshCommunities.mockClear();
    communityRole = "superadmin";
    grantSettingsLevel = null;
    communityId = 4;
    settings = baseSettings();
    secondFactorAvailable = true;
    guestsEnabled = false;
    connections = [
      connection(1, 11, "corp", "Corp SSO"),
      connection(2, 12, "contractors", "Contractors"),
    ];
    connectable = [{ id: 11, slug: "corp", display_name: "Corp SSO" }];
  });

  describe("how the page is laid out", () => {
    /** Where each snippet falls in the rendered text, so order can be read. */
    const positions = (...snippets: string[]) => {
      const text = document.body.textContent ?? "";
      return snippets.map((snippet) => text.indexOf(snippet));
    };

    it("puts the rules first, then the providers, their groups and privacy", () => {
      render();

      const found = positions("Sign-in rules", "Sign-in providers", "Group rules", "Privacy");
      expect(found.every((index) => index >= 0)).toBe(true);
      expect(found).toEqual([...found].sort((a, b) => a - b));
    });

    it("states each rule as it stands, with a way to change it", () => {
      savedPolicy({
        provider_id: 12,
        provider_display_name: "Contractors",
        require_methods: ["passkey"],
      });
      stored({ require_second_factor: true });
      render();

      expect(screen.getByText("Through Contractors, with a passkey")).toBeInTheDocument();
      expect(screen.getByText("Required in each session")).toBeInTheDocument();
      expect(screen.getByText(/your server's session length applies/i)).toBeInTheDocument();
      // Nothing that decides who gets in is a switch on the page.
      expect(screen.getByRole("button", { name: "Change Members" })).toBeEnabled();
      expect(screen.queryByRole("switch", { name: /second factor/i })).not.toBeInTheDocument();
    });
  });

  describe("a community that has connected nothing", () => {
    it("says so where the connections would be, and offers the way in", () => {
      connections = [];
      render();

      expect(screen.getByText("Nothing connected yet")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Set up sign-in" })).toBeEnabled();
      // A group rule names a provider, so there is nothing to write one against.
      expect(screen.queryByText("Group rules")).not.toBeInTheDocument();
    });

    it("says the deployment offers none, rather than inviting a choice of none", () => {
      connections = [];
      connectable = [];
      render();

      expect(screen.getByText(/has not offered any providers/i)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Set up sign-in" })).not.toBeInTheDocument();
    });

    it("says nothing about it once something is connected", () => {
      render();

      expect(screen.queryByText("Nothing connected yet")).not.toBeInTheDocument();
      // The way in stays: a community may connect a second provider.
      expect(screen.getByRole("button", { name: /connect a provider/i })).toBeInTheDocument();
    });
  });

  describe("choosing what the community requires", () => {
    // One rule, expressed by ticking what it asks for. `require_methods` is
    // sent rather than omitted: switching to a named provider is also how a
    // method requirement is cleared, so the empty list is the instruction.
    // A second factor is not among them — it is its own rule, which a
    // community with no requirement at all still has.
    it.each([
      [
        "'any of ours' as a rule that names no provider",
        "Any of our sign-in providers",
        [],
        { require_methods: ["sso"] },
      ],
      [
        "a named provider as a rule that names no method",
        "Contractors",
        [],
        { provider_id: 12, require_methods: [] },
      ],
      [
        "a passkey alongside a named provider",
        "Contractors",
        [/require a passkey/i],
        { provider_id: 12, require_methods: ["passkey"] },
      ],
      [
        "a passkey on its own",
        null,
        [/require a passkey/i],
        { provider_id: null, require_methods: ["passkey"] },
      ],
    ])("saves %s", async (_label, provider, ticks, sent) => {
      const user = mounted();

      await change(user, "Members");
      await user.click(requirementRadio());
      if (provider) await chooseOption(user, provider);
      for (const tick of ticks) await user.click(screen.getByLabelText(tick));
      await user.click(screen.getByRole("button", { name: "Save requirement" }));

      expect(save).toHaveBeenCalledTimes(1);
      expect(save.mock.calls[0][0]).toEqual({ auth_policy: { policy: "required", ...sent } });
    });

    it("switches back from 'any of ours' to a named provider", async () => {
      savedPolicy({ require_methods: ["sso"] });
      const user = mounted();

      await change(user, "Members");
      await chooseOption(user, "Corp SSO");
      await user.click(screen.getByRole("button", { name: "Save requirement" }));

      expect(save.mock.calls[0][0]).toEqual({
        auth_policy: { policy: "required", provider_id: 11, require_methods: [] },
      });
    });

    it("has nothing to save until something changes", async () => {
      savedPolicy({ require_methods: ["sso"] });
      const user = mounted();

      await change(user, "Members");

      expect(screen.getByRole("button", { name: "Save requirement" })).toBeDisabled();
    });

    it("says who it reaches before it saves, leaving out what reaches nobody", async () => {
      stored({
        member_figures: figures({
          total: 48,
          without_passkey: 9,
          never_through: [
            { provider_id: 11, count: 0 },
            { provider_id: 12, count: 31 },
          ],
        }),
      });
      const user = mounted();

      await change(user, "Members");
      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");

      expect(screen.getByText("When you save")).toBeInTheDocument();
      expect(
        screen.getByText(/asked to sign in through Contractors the next time they open Test/i)
      ).toBeInTheDocument();
      expect(
        screen.getByText("31 of 48 members have never signed in through Contractors.")
      ).toBeInTheDocument();
      expect(screen.queryByText(/hold no passkey/i)).not.toBeInTheDocument();

      await user.click(screen.getByLabelText(/require a passkey/i));
      expect(screen.getByText("9 of 48 members hold no passkey yet.")).toBeInTheDocument();

      // Everybody has been through Corp SSO already, so that line goes.
      await chooseOption(user, "Corp SSO");
      expect(screen.queryByText(/have never signed in/i)).not.toBeInTheDocument();
    });

    it("offers only the open choice when nothing can be required", async () => {
      connections = [{ ...connection(1, 11, "corp", "Corp SSO"), enabled: false }];
      const user = mounted();

      await change(user, "Members");

      expect(screen.queryByLabelText(/through our providers/i)).not.toBeInTheDocument();
      expect(screen.getByText(/connect a provider under sign-in providers/i)).toBeInTheDocument();
    });
  });

  describe("who may reach it", () => {
    it.each<CommunityRole>(["admin", "member"])("shows %s nothing at all", (role) => {
      // The whole page is the seat's, so there is nothing here to render
      // for anybody else. The tab is hidden the same way; this is the
      // direct-URL half.
      communityRole = role;
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });

    it("gives a superadmin settings grantee the current controls", () => {
      grantSettingsLevel = "superadmin";
      stored({ enforce_compliance_session: true });

      render();

      expect(screen.getByRole("button", { name: "Change Members" })).toBeEnabled();
      expect(screen.getByText(/sign in again everywhere on this server/i)).toBeInTheDocument();
    });

    it("waits for the settings rather than reading 'granted nothing' off a pending answer", () => {
      settings = undefined;
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });
  });

  describe("asking for a second factor", () => {
    // Its own rule, because a community that asks nothing about how people
    // arrive may still ask them to hold a factor — and choosing "open"
    // deletes the requirement entirely.
    const required = () => screen.getByRole("radio", { name: "Required in each session" });

    it("saves on its own, naming no method, after saying who it reaches", async () => {
      stored({
        member_figures: figures({ total: 48, without_factor: 9 }),
        guest_figures: figures({ total: 12, without_factor: 3 }),
      });
      const user = mounted();

      expect(screen.getByText("Not required")).toBeInTheDocument();
      await change(user, "Second factor");
      await user.click(required());

      expect(screen.getByText(/guests included/i)).toBeInTheDocument();
      expect(
        screen.getByText("12 of 60 people here hold no authenticator or passkey yet.")
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Save" }));

      // Not folded into the sign-in requirement, which is a separate save.
      expect(save).toHaveBeenCalledTimes(1);
      expect(save).toHaveBeenCalledWith({ require_second_factor: true }, expect.anything());
    });

    it("asks for a code when the admin's own session has none", async () => {
      const asked: FactorChallengeDetail[] = [];
      const record = (event: Event) => {
        asked.push((event as CustomEvent<FactorChallengeDetail>).detail);
      };
      window.addEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);
      const user = mounted();

      await change(user, "Second factor");
      await user.click(required());
      await user.click(screen.getByRole("button", { name: "Save" }));
      refuse("totp");

      expect(screen.getByText(/enter a code from your authenticator app/i)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Enter a code" }));
      window.removeEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);

      expect(asked).toEqual([{ communityId: 4, kind: "totp" }]);
      // The choice is still there to save again once the session carries it.
      expect(required()).toBeChecked();
    });

    it("is shown, not offered, where the deployment already asks everybody", () => {
      savedPolicy({ policy: "open", factor_required_by_platform: true });
      render();

      expect(screen.getByText("Required in each session")).toBeInTheDocument();
      expect(screen.getByText("Set by your server")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Change Second factor" })).toBeNull();
    });

    it("is shown, not offered, where whoever runs the server sets it", () => {
      stored({ require_second_factor: true, set_by_deployment: ["require_second_factor"] });
      render();

      expect(screen.getByText("Required in each session")).toBeInTheDocument();
      expect(screen.getAllByText("Set by your server")).toHaveLength(1);
      expect(screen.queryByRole("button", { name: "Change Second factor" })).toBeNull();
    });

    it("is not offered where the deployment permits no kind of factor", () => {
      secondFactorAvailable = false;
      render();

      expect(screen.queryByText("Second factor")).not.toBeInTheDocument();
    });
  });

  describe("privacy", () => {
    const rankingSwitch = () =>
      screen.queryByRole("switch", { name: /rank search by engagement/i });

    it("saves a switch as it is flipped", async () => {
      const user = mounted();

      await user.click(rankingSwitch() as HTMLElement);

      expect(save).toHaveBeenCalledWith({ allow_engagement_ranking: false }, expect.anything());
    });

    it("shows the server's answer, not a switch, where the server has given one", () => {
      stored({
        engagement_ranking_allowed_by_platform: false,
        allow_email_notifications: false,
        set_by_deployment: ["allow_email_notifications"],
      });
      render();

      expect(rankingSwitch()).not.toBeInTheDocument();
      expect(screen.getByText(/turned engagement ranking off/i)).toBeInTheDocument();
      expect(screen.queryByRole("switch", { name: /email notifications/i })).toBeNull();
      expect(screen.getAllByText("Set by your server")).toHaveLength(2);
    });
  });

  describe("when the admin's own session does not meet the rule", () => {
    /** What the page asked the global dialog for, if it asked. */
    let asked: FactorChallengeDetail[] = [];
    const record = (event: Event) => {
      asked.push((event as CustomEvent<FactorChallengeDetail>).detail);
    };
    beforeEach(() => {
      asked = [];
      window.addEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);
    });
    afterEach(() => {
      window.removeEventListener(AUTH_FACTOR_REQUIRED_EVENT, record);
    });

    it("offers the named provider's sign-in", async () => {
      const user = mounted();

      await change(user, "Members");
      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByRole("button", { name: "Save requirement" }));
      refuse("provider");

      expect(screen.getByText(/hasn't signed in with Contractors/i)).toBeInTheDocument();
      // The choice is still there to save again once the session carries it.
      expect(screen.getByRole("combobox")).toHaveTextContent("Contractors");
      expect(screen.getByRole("button", { name: "Save requirement" })).toBeEnabled();
    });

    // What the rule wanted is what the page asks the global dialog for, and
    // the unsaved choice survives the asking.
    it("asks for the passkey where the rule wants one", async () => {
      const user = mounted();

      await change(user, "Members");
      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: "Save requirement" }));
      refuse("passkey");

      expect(screen.getByText(/present your passkey first/i)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^present passkey$/i }));

      expect(asked).toEqual([{ communityId: 4, kind: "passkey" }]);
      expect(screen.getByLabelText(/require a passkey/i)).toBeChecked();
      expect(screen.getByRole("button", { name: "Save requirement" })).toBeEnabled();
    });

    it("still says something when the server names nothing", async () => {
      // A refusal that names nothing still gets its own line.
      const user = mounted();

      await change(user, "Members");
      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: "Save requirement" }));
      refuse();

      expect(
        screen.getByText(/meet this requirement yourself before asking it of others/i)
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/require a passkey/i)).toBeChecked();
      expect(screen.getByRole("button", { name: "Save requirement" })).toBeEnabled();
    });
  });

  describe("what each grant brings with it", () => {
    const SESSION = "Sign in again every 12 hours";
    const REQUIREMENT = "Members";
    const SIGN_IN_LINK = "Member sign-in link";
    const PROVIDERS = "Sign-in providers";
    const PRIVACY = "Privacy";

    // Each grant is its own sections and rows, and neither brings the other's.
    it.each<[string, CommunityAuthOption[], string[], string[]]>([
      ["neither, so nothing at all", [], [], [SESSION, REQUIREMENT, SIGN_IN_LINK]],
      ["only the restrictions", ["restrictions"], [SESSION, PRIVACY], [PROVIDERS, REQUIREMENT]],
      ["only the providers", ["providers"], [REQUIREMENT, SIGN_IN_LINK], [PRIVACY, SESSION]],
    ])("shows %s where that is what the operator granted", (_label, granted, shown, hidden) => {
      stored({ auth_options: granted });
      const { container } = render();

      if (shown.length === 0) expect(container).toBeEmptyDOMElement();
      for (const text of shown) expect(screen.getByText(text)).toBeInTheDocument();
      for (const text of hidden) expect(screen.queryByText(text)).not.toBeInTheDocument();
    });
  });

  describe("how often members sign in again", () => {
    it("turns on in its dialog, saying it reaches past this community", async () => {
      const user = mounted();

      await change(user, "Sign in again every 12 hours");
      await user.click(screen.getByRole("radio", { name: "Sign in again every 12 hours" }));
      expect(screen.getByText(/in every community on this server/i)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(save).toHaveBeenCalledTimes(1);
      expect(save.mock.calls[0][0]).toEqual({ enforce_compliance_session: true });
    });

    it("is the seat's, not an ordinary admin's", () => {
      communityRole = "admin";
      render();

      expect(screen.queryByText("Sign in again every 12 hours")).not.toBeInTheDocument();
    });
  });

  describe("guests", () => {
    beforeEach(() => {
      guestsEnabled = true;
    });

    it("saves the guests' own sign-in requirement, counting the guests it reaches", async () => {
      stored({
        guest_figures: figures({ total: 5, never_through: [{ provider_id: 12, count: 2 }] }),
      });
      const user = mounted();

      await change(user, "Guests");
      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      expect(
        screen.getByText("2 of 5 guests have never signed in through Contractors.")
      ).toBeInTheDocument();
      // The guests' rule is not asked of whoever writes it.
      expect(screen.queryByText(/if your own session/i)).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Save requirement" }));

      expect(save.mock.calls[0][0]).toEqual({
        guest_auth_policy: { policy: "required", provider_id: 12, require_methods: [] },
      });
    });

    it("saves the longest stay, below the server's limit", async () => {
      const user = mounted();

      expect(screen.getByText("90 days")).toBeInTheDocument();
      await change(user, "Longest guest stay");
      expect(screen.getByText(/server's limit of 90 days/i)).toBeInTheDocument();
      await user.type(screen.getByLabelText("Longest a guest may stay (days)"), "30");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(save.mock.calls[0][0]).toEqual({ guest_max_days: 30 });
    });

    it("clears a stay of its own back to the server's limit", async () => {
      stored({ guest_max_days: 30 });
      const user = mounted();

      expect(screen.getByText(/your server allows up to 90/i)).toBeInTheDocument();
      await change(user, "Longest guest stay");
      await user.clear(screen.getByLabelText("Longest a guest may stay (days)"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(save.mock.calls[0][0]).toEqual({ guest_max_days: null });
    });

    it("says nothing about guests where the community takes none", () => {
      guestsEnabled = false;
      render();

      expect(screen.queryByText("Guests")).not.toBeInTheDocument();
      expect(screen.queryByText("Longest guest stay")).not.toBeInTheDocument();
    });
  });
});

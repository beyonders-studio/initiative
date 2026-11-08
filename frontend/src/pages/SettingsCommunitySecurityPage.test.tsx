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
  useOrderCustomRoleClaimRules: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { SettingsCommunitySecurityPage } from "./SettingsCommunitySecurityPage";

const render = () =>
  renderWithProviders(<SettingsCommunitySecurityPage />, { auth: { user: buildUser() } });

const requirementRadio = () => screen.getByLabelText(/require single sign-on/i);

/** Render the page, ready to be clicked. */
const mounted = () => {
  const user = userEvent.setup();
  render();
  return user;
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

describe("SettingsCommunitySecurityPage", () => {
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

    it("puts who gets in before the terms of a session", () => {
      render();

      const [whoGetsIn, onWhatTerms] = positions("Who gets in", "On what terms");
      expect(whoGetsIn).toBeGreaterThanOrEqual(0);
      expect(onWhatTerms).toBeGreaterThan(whoGetsIn);
    });

    it("asks for a requirement after the connections it can name", () => {
      // The requirement picks from the providers above it, and the rules
      // between them say where the people arriving on those providers land.
      render();

      const found = positions(
        "Which sign-ins are yours",
        "Where your people land",
        "Sign-in requirement",
        "Member sign-in link"
      );
      expect(found.every((index) => index >= 0)).toBe(true);
      expect(found).toEqual([...found].sort((a, b) => a - b));
    });
  });

  describe("a community that has connected nothing", () => {
    // The prompt used to be a card of its own above the sections. It is now the
    // connections card saying so, with the way in beside it.
    it("says so where the connections would be, and offers the way in", () => {
      connections = [];
      render();

      expect(screen.getByText(/no providers connected yet/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /connect a provider/i })).toBeEnabled();
    });

    it("says the deployment offers none, rather than inviting a choice of none", () => {
      connections = [];
      connectable = [];
      render();

      expect(screen.getByText(/has not offered any providers/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /connect a provider/i })).toBeDisabled();
    });

    it("says nothing about it once something is connected", () => {
      render();

      expect(screen.queryByText(/no providers connected yet/i)).not.toBeInTheDocument();
      // The way in stays: a community may connect a second provider.
      expect(screen.getByRole("button", { name: /connect a provider/i })).toBeInTheDocument();
    });
  });

  describe("choosing what the community requires", () => {
    // One rule, expressed by ticking what it asks for. `require_methods` is
    // sent rather than omitted: switching to a named provider is also how a
    // method requirement is cleared, so the empty list is the instruction.
    // A second factor is not among them — it is asked for in the terms a
    // session is held to, which a community with no rule at all still has.
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

      await user.click(requirementRadio());
      if (provider) await chooseOption(user, provider);
      for (const tick of ticks) await user.click(screen.getByLabelText(tick));
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(save).toHaveBeenCalledTimes(1);
      expect(save.mock.calls[0][0]).toEqual({ auth_policy: { policy: "required", ...sent } });
    });

    it("switches back from 'any of ours' to a named provider", async () => {
      savedPolicy({ require_methods: ["sso"] });
      const user = mounted();

      await chooseOption(user, "Corp SSO");
      await user.click(screen.getByRole("button", { name: /save/i }));

      expect(save.mock.calls[0][0]).toEqual({
        auth_policy: { policy: "required", provider_id: 11, require_methods: [] },
      });
    });

    it("has nothing to save until something changes", () => {
      savedPolicy({ require_methods: ["sso"] });
      render();

      expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    });
  });

  describe("who may reach it", () => {
    it.each<CommunityRole>(["admin", "member"])("shows %s nothing at all", (role) => {
      // The whole page is the seat's, so there is nothing here to render
      // read-only. The tab is hidden the same way; this is the direct-URL half.
      communityRole = role;
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });

    it("leaves the superadmin's own controls alone", () => {
      render();
      expect(requirementRadio()).not.toBeDisabled();
    });

    it("gives a superadmin settings grantee the current controls", () => {
      grantSettingsLevel = "superadmin";
      stored({ enforce_compliance_session: true });

      render();

      expect(requirementRadio()).toBeInTheDocument();
      expect(screen.getByLabelText(/sign in again every twelve hours/i)).toBeChecked();
    });

    it("waits for the settings rather than reading 'granted nothing' off a pending answer", () => {
      settings = undefined;
      const { container } = render();

      expect(container).toBeEmptyDOMElement();
    });
  });

  describe("asking for a second factor", () => {
    // Its own control, in the terms a session is held to, because a community
    // that asks nothing about how people arrive may still ask them to hold a
    // factor — and choosing "open" deletes the rule row entirely.
    const factorSwitch = () => screen.getByLabelText(/require a second factor/i);

    it("is offered without asking anything about how people arrive", () => {
      render();

      expect(factorSwitch()).toBeInTheDocument();
      expect(factorSwitch()).not.toBeChecked();
    });

    it("saves on its own, naming no method", async () => {
      const user = mounted();

      await user.click(factorSwitch());

      // Not folded into the sign-in rule, which is a separate save.
      expect(save).toHaveBeenCalledTimes(1);
      expect(save).toHaveBeenCalledWith({ require_second_factor: true }, expect.anything());
    });

    it("reads what the community already asks for", () => {
      stored({ require_second_factor: true });
      render();

      expect(factorSwitch()).toBeChecked();
    });

    it("is held where the deployment already asks everybody", () => {
      // Its own answer has nothing to add, so it shows the deployment's and
      // stops rather than offering a tick that would change nothing.
      savedPolicy({ policy: "open", factor_required_by_platform: true });
      render();

      expect(factorSwitch()).toBeChecked();
      expect(factorSwitch()).toBeDisabled();
      expect(screen.getByText(/already asks everybody/i)).toBeInTheDocument();
    });

    it("is shown, not offered, where whoever runs the server sets it", () => {
      stored({ require_second_factor: true, set_by_deployment: ["require_second_factor"] });
      render();

      expect(factorSwitch()).toBeChecked();
      expect(factorSwitch()).toBeDisabled();
      expect(screen.getAllByText(/sets this for your community/i)).toHaveLength(1);
    });

    it("is not offered where the deployment permits no kind of factor", () => {
      secondFactorAvailable = false;
      render();

      expect(screen.queryByLabelText(/require a second factor/i)).not.toBeInTheDocument();
    });
  });

  describe("ranking search by engagement", () => {
    const rankingSwitch = () => screen.getByLabelText(/rank search results by community/i);

    it("saves on its own", async () => {
      const user = mounted();

      await user.click(rankingSwitch());

      expect(save).toHaveBeenCalledWith({ allow_engagement_ranking: false }, expect.anything());
    });

    it("is held where the deployment has turned it off", () => {
      stored({ engagement_ranking_allowed_by_platform: false });
      render();

      expect(rankingSwitch()).not.toBeChecked();
      expect(rankingSwitch()).toBeDisabled();
      expect(screen.getByText(/turned engagement ranking off/i)).toBeInTheDocument();
    });
  });

  describe("when the admin's own session does not meet the rule", () => {
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

      await user.click(requirementRadio());
      await chooseOption(user, "Contractors");
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse("provider");

      expect(screen.getByText(/hasn't signed in with Contractors/i)).toBeInTheDocument();
      // The choice is still there to save again once the session carries it.
      expect(screen.getByRole("combobox")).toHaveTextContent("Contractors");
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });

    // What the rule wanted is what the page asks the global dialog for, and
    // the unsaved choice survives the asking either way. A second factor is
    // not among them: it is asked for on its own control now, which saves by
    // itself rather than through this form.
    it.each([
      [
        "the passkey",
        /require a passkey/i,
        "passkey",
        /present your passkey first/i,
        /^present passkey$/i,
      ],
    ])("asks for %s where the rule wants one", async (_label, tick, unmet, says, offers) => {
      const user = mounted();

      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(tick));
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse(unmet);

      expect(screen.getByText(says)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: offers }));

      expect(asked).toEqual([{ communityId: 4, kind: unmet }]);
      expect(screen.getByLabelText(tick)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });

    it("still says something when the server names nothing", async () => {
      // A refusal that names nothing still gets its own line.
      const user = mounted();

      await user.click(requirementRadio());
      await user.click(screen.getByLabelText(/require a passkey/i));
      await user.click(screen.getByRole("button", { name: /save/i }));
      refuse();

      expect(
        screen.getByText(/meet this requirement yourself before asking it of others/i)
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/require a passkey/i)).toBeChecked();
      expect(screen.getByRole("button", { name: /save/i })).toBeEnabled();
    });
  });

  describe("what each grant brings with it", () => {
    const SESSION = { label: /sign in again every twelve hours/i };
    const REQUIREMENT = { label: /require single sign-on/i };
    const SIGN_IN_LINK = { text: /member sign-in link/i };
    const WHO_GETS_IN = { text: "Who gets in" };
    const ON_WHAT_TERMS = { text: "On what terms" };

    /** A thing on the page, however it is named there. */
    const find = (q: { label: RegExp } | { text: string | RegExp }) =>
      "label" in q ? screen.queryByLabelText(q.label) : screen.queryByText(q.text);
    type Probe = Parameters<typeof find>[0];

    // Each grant is one half of the page, and neither brings the other with it.
    it.each<[string, CommunityAuthOption[], Probe[], Probe[]]>([
      ["neither, so nothing at all", [], [], [SESSION, REQUIREMENT, SIGN_IN_LINK]],
      ["only the terms half", ["restrictions"], [SESSION], [WHO_GETS_IN, REQUIREMENT]],
      [
        "only the sign-in half",
        ["providers"],
        [REQUIREMENT, SIGN_IN_LINK],
        [ON_WHAT_TERMS, SESSION],
      ],
    ])("shows %s where that is what the operator granted", (_label, granted, shown, hidden) => {
      stored({ auth_options: granted });
      const { container } = render();

      if (shown.length === 0) expect(container).toBeEmptyDOMElement();
      for (const q of shown) expect(find(q)).toBeInTheDocument();
      for (const q of hidden) expect(find(q)).not.toBeInTheDocument();
    });
  });

  // The switch is the seat's, and saves the moment it is flipped — there is
  // no button to press after.
  describe.each([
    {
      what: "how often members sign in again",
      control: () => screen.queryByLabelText(/sign in again every twelve hours/i),
      startsOn: false,
      store: (value: boolean) => stored({ enforce_compliance_session: value }),
      sends: { enforce_compliance_session: true },
      explains: /cap how long people stay signed in/i,
    },
  ])("$what", ({ control, startsOn, store, sends, explains }) => {
    it("saves as it is switched, with no button to press", async () => {
      const user = mounted();

      if (startsOn) expect(control()).toBeChecked();
      else expect(control()).not.toBeChecked();
      await user.click(control() as HTMLElement);

      expect(save).toHaveBeenCalledTimes(1);
      expect(save.mock.calls[0][0]).toEqual(sends);
    });

    it("shows what the community chose, and says in one line what it means", () => {
      store(!startsOn);
      render();

      if (startsOn) expect(control()).not.toBeChecked();
      else expect(control()).toBeChecked();
      expect(screen.getByText(explains)).toBeInTheDocument();
    });

    it("is the seat's, not an ordinary admin's", () => {
      communityRole = "admin";
      render();

      expect(control()).not.toBeInTheDocument();
    });
  });

  describe("guests", () => {
    beforeEach(() => {
      guestsEnabled = true;
    });

    it("saves the guests' own sign-in requirement", async () => {
      const user = mounted();

      // The second of each control is the guests'.
      await user.click(screen.getAllByLabelText(/require single sign-on/i)[1]);
      await chooseOption(user, "Contractors");
      await user.click(
        screen.getByRole("button", { name: "Save the guests' sign-in requirement" })
      );

      expect(save.mock.calls[0][0]).toEqual({
        guest_auth_policy: { policy: "required", provider_id: 12, require_methods: [] },
      });
    });

    it("saves the longest stay, below the server's limit", async () => {
      const user = mounted();
      const days = screen.getByLabelText("Longest a guest may stay (days)");
      expect(screen.getByText(/server's limit of 90 days/i)).toBeInTheDocument();

      await user.type(days, "30");
      await user.click(screen.getByRole("button", { name: "Save the longest guest stay" }));
      expect(save.mock.calls[0][0]).toEqual({ guest_max_days: 30 });
    });

    it("clears a stay of its own back to the server's limit", async () => {
      stored({ guest_max_days: 30 });
      const user = mounted();

      await user.clear(screen.getByLabelText("Longest a guest may stay (days)"));
      await user.click(screen.getByRole("button", { name: "Save the longest guest stay" }));

      expect(save.mock.calls[0][0]).toEqual({ guest_max_days: null });
    });

    it("says nothing about guests where the community takes none", () => {
      guestsEnabled = false;
      render();

      expect(screen.queryByText("Guests' sign-in requirement")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Longest a guest may stay (days)")).not.toBeInTheDocument();
    });
  });

  describe("how often members sign in again, across communities", () => {
    const limitSwitch = () => screen.getByLabelText(/sign in again every twelve hours/i);

    it("does not carry a pending choice or failure into another community", async () => {
      const user = userEvent.setup();
      const view = render();

      await user.click(limitSwitch());
      const pending = save.mock.calls[0]?.[1] as {
        onError: (error: unknown) => void;
      };

      communityId = 5;
      view.rerender(<SettingsCommunitySecurityPage />);

      expect(limitSwitch()).not.toBeChecked();

      act(() => pending.onError(new Error("old community failed")));
      expect(screen.queryByText("Could not save the session limit")).not.toBeInTheDocument();
    });
  });
});

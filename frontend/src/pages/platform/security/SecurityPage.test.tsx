import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  CaptchaSettingsResponse,
  PlatformAuthSettingsResponse,
  PlatformAuthSettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";

const authMutate = vi.fn();
const captchaMutate = vi.fn();
const providerMutate = vi.fn();

/** The last write to the sign-in rules, with the handlers of the hook that sent it. */
let lastWrite:
  | {
      options?: { onError?: (error: unknown, variables: PlatformAuthSettingsUpdate) => void };
      variables: PlatformAuthSettingsUpdate;
    }
  | undefined;

let settings: PlatformAuthSettingsResponse;
let captcha: CaptchaSettingsResponse;
let providers: { id: number; display_name: string; asserts_second_factor: boolean }[];

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdatePlatformAuthSettings: (options?: {
    onError?: (error: unknown, variables: PlatformAuthSettingsUpdate) => void;
  }) => ({
    mutate: (variables: PlatformAuthSettingsUpdate) => {
      authMutate(variables);
      lastWrite = { options, variables };
    },
    isPending: false,
  }),
  useCaptchaSettings: () => ({ data: captcha, isLoading: false }),
  useUpdateCaptchaSettings: () => ({ mutate: captchaMutate, isPending: false }),
  // The mirror beside the second-factor rule: which providers' own account of
  // a sign-in counts as presenting one.
  useAuthProviders: () => ({ data: providers, isLoading: false }),
  useUpdateAuthProvider: () => ({ mutate: providerMutate, isPending: false }),
  useNotificationSettings: () => ({ data: undefined, isLoading: false }),
  useUpdateNotificationSettings: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { SecurityPage } from "./SecurityPage";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, primary: true, answers_factor: false, would_strand: 0 },
    { method: "totp", enabled: true, primary: false, answers_factor: true, would_strand: 0 },
    { method: "passkey", enabled: true, primary: true, answers_factor: true, would_strand: 0 },
  ],
  communities_requiring_sign_in: 0,
  session_max_hours: null,
  session_idle_minutes: null,
  second_factor_requirement: "nobody",
  breached_password_check_enabled: true,
  accounts_without_factor: { platform_roles: 2, everyone: 9 },
  // Something can answer the requirement; the case where nothing can has its
  // own test below.
  factor_methods_permitted: true,
};

const baseCaptcha: CaptchaSettingsResponse = {
  provider: "turnstile",
  site_key: "site-key",
  has_secret_key: true,
  enforcing: true,
};

/** The server refusing because this account does not meet the rule itself. */
const selfUnsatisfied = (): AxiosError => {
  const error = new AxiosError("refused");
  error.response = {
    status: 400,
    statusText: "Bad Request",
    data: { detail: "AUTH_RULE_SELF_UNSATISFIED" },
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

const renderPage = () =>
  renderWithProviders(<SecurityPage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });

/** Open a sign-in rule's dialog from its row. */
const change = (rule: string) =>
  fireEvent.click(screen.getByRole("button", { name: `Change ${rule}` }));

const save = () => screen.getByRole("button", { name: "Save" });

beforeEach(() => {
  vi.clearAllMocks();
  lastWrite = undefined;
  settings = structuredClone(base);
  captcha = structuredClone(baseCaptcha);
  providers = [
    { id: 1, display_name: "Corp SSO", asserts_second_factor: false },
    { id: 2, display_name: "Entra", asserts_second_factor: true },
  ];
});

describe("the sign-in rules", () => {
  it("states each rule's current value", () => {
    settings = { ...base, session_max_hours: 24, session_idle_minutes: 30 };
    renderPage();

    expect(screen.getByText("Nobody has to")).toBeInTheDocument();
    expect(screen.getByText("Authenticator app and Passkey")).toBeInTheDocument();
    expect(screen.getByText("24 hours")).toBeInTheDocument();
    expect(screen.getByText(/idle sessions end after 30 minutes/)).toBeInTheDocument();
    expect(screen.getByText("Cloudflare Turnstile")).toBeInTheDocument();
  });
});

describe("second factor", () => {
  it("starts on the stored answer", () => {
    settings = { ...base, second_factor_requirement: "platform_roles" };
    renderPage();
    change("Second factor");

    expect(screen.getByRole("radio", { name: /platform role/i })).toBeChecked();
  });

  it("saves the answer that was chosen, and offers to present a factor when this account has none", () => {
    renderPage();
    change("Second factor");

    // Nothing to save, and no cost to state, while nobody is asked.
    expect(save()).toBeDisabled();
    expect(screen.queryByText("When you save")).not.toBeInTheDocument();
    expect(screen.queryByText(/personal API keys/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({ second_factor_requirement: "everyone" });

    act(() => lastWrite?.options?.onError?.(selfUnsatisfied(), lastWrite.variables));

    expect(screen.getByText(/set up a second factor of your own/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enter a code/i })).toBeInTheDocument();
  });

  it("says how many people the chosen answer would ask", () => {
    renderPage();
    change("Second factor");

    fireEvent.click(screen.getByRole("radio", { name: /platform role/i }));
    const note = screen.getByRole("note");
    expect(within(note).getByText("When you save")).toBeInTheDocument();
    expect(within(note).getByText(/2 people don't have one yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    expect(screen.getByText(/9 people don't have one yet/i)).toBeInTheDocument();
  });

  it("leaves out a count of nobody", () => {
    settings = { ...base, accounts_without_factor: { platform_roles: 0, everyone: 0 } };
    renderPage();
    change("Second factor");

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));

    expect(screen.queryByText(/don't have one yet/i)).not.toBeInTheDocument();
    expect(screen.getByText(/personal API keys/i)).toBeInTheDocument();
  });

  it("cannot be changed while nothing could answer it", () => {
    settings = { ...base, factor_methods_permitted: false };
    renderPage();

    // The server refuses this write; the row says so rather than offering it.
    expect(screen.getByText(/offer the authenticator app or passkeys first/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change Second factor" })).toBeNull();
  });

  describe("which providers' word counts", () => {
    it("lists the providers with the answer each holds, and writes it as the provider's own page does", async () => {
      const user = userEvent.setup();
      renderPage();
      change("Second factor");

      expect(screen.getByLabelText("Corp SSO")).not.toBeChecked();
      expect(screen.getByLabelText("Entra")).toBeChecked();
      await user.click(screen.getByLabelText("Corp SSO"));

      expect(providerMutate).toHaveBeenCalledWith({
        providerId: 1,
        data: { asserts_second_factor: true },
      });
    });

    it("says nothing where the deployment has registered none", () => {
      providers = [];
      renderPage();
      change("Second factor");

      expect(screen.queryByText(/providers whose sign-in counts/i)).not.toBeInTheDocument();
    });
  });
});

describe("second factors offered", () => {
  it("shows the passkey as its value, set under Ways in", () => {
    renderPage();
    change("Second factors offered");

    expect(screen.queryByRole("checkbox", { name: "Passkey" })).toBeNull();
    expect(screen.getByText("Set under Ways in")).toBeInTheDocument();
  });

  it("withdraws the authenticator app and keeps every other way in", () => {
    renderPage();
    change("Second factors offered");

    fireEvent.click(screen.getByRole("checkbox", { name: "Authenticator app" }));
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({ methods: ["password", "passkey"] });
  });
});

describe("session length", () => {
  it("starts blank when the deployment asks for no limit", () => {
    renderPage();
    expect(screen.getByText("No limit")).toBeInTheDocument();
    change("Session length");

    expect(screen.getByLabelText(/hours/i)).toHaveValue(null);
  });

  // Both halves of the answer go in one write; an emptied field clears its limit.
  it.each([
    [null, /hours/i, "12", { session_max_hours: 12, session_idle_minutes: null }],
    [12, /hours/i, "", { session_max_hours: null, session_idle_minutes: null }],
    [null, /idle minutes/i, "20", { session_max_hours: null, session_idle_minutes: 20 }],
  ])("saves from %s, setting %s to %o", (stored, field, value, written) => {
    settings = { ...base, session_max_hours: stored };
    renderPage();
    change("Session length");

    fireEvent.change(screen.getByLabelText(field), { target: { value } });
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith(written);
  });

  it("will not save an unchanged or fractional limit", () => {
    settings = { ...base, session_max_hours: 12 };
    renderPage();
    change("Session length");

    expect(save()).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "1.5" } });
    expect(save()).toBeDisabled();
  });
});

describe("breached password check", () => {
  // Off for a server that cannot reach the internet, and back on.
  it.each([
    [true, /don't check/i],
    [false, "Check new passwords against known breaches"],
  ])("turns the check over from %s", (enabled, answer) => {
    settings = { ...base, breached_password_check_enabled: enabled };
    renderPage();
    change("Breached password check");

    fireEvent.click(screen.getByRole("radio", { name: answer }));
    fireEvent.click(save());

    // Only its own field: the other sign-in rules are left as they are.
    expect(authMutate).toHaveBeenCalledWith({ breached_password_check_enabled: !enabled });
  });
});

describe("captcha", () => {
  // A secret left blank keeps the saved one; one that was typed is sent.
  it.each([
    [/site key/i, "new-site", { provider: "turnstile", site_key: "new-site" }],
    [
      /secret key/i,
      "s3cret",
      { provider: "turnstile", site_key: "site-key", secret_key: "s3cret" },
    ],
  ])("saves %s typed as %s", (field, value, written) => {
    renderPage();
    change("Captcha");

    fireEvent.change(screen.getByLabelText(field), { target: { value } });
    fireEvent.click(save());

    expect(captchaMutate).toHaveBeenCalledWith(written);
  });

  it("says when a provider is chosen but the captcha is not on", () => {
    captcha = { ...baseCaptcha, has_secret_key: false, enforcing: false };
    renderPage();
    expect(
      screen.getByText(/not on until its site key and secret key are saved/)
    ).toBeInTheDocument();
    change("Captcha");

    expect(screen.getByText(/comes on once/i)).toBeInTheDocument();
  });
});

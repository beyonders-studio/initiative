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

  it("says a captcha without its keys is not on", () => {
    captcha = { ...baseCaptcha, has_secret_key: false, enforcing: false };
    renderPage();

    expect(
      screen.getByText(/not on until its site key and secret key are saved/)
    ).toBeInTheDocument();
  });
});

describe("second factor", () => {
  it("starts on the stored answer", () => {
    settings = { ...base, second_factor_requirement: "platform_roles" };
    renderPage();
    change("Second factor");

    expect(screen.getByRole("radio", { name: /platform role/i })).toBeChecked();
  });

  it("will not save the answer that is already stored", () => {
    renderPage();
    change("Second factor");

    expect(save()).toBeDisabled();
  });

  it("saves the answer that was chosen", () => {
    renderPage();
    change("Second factor");

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({ second_factor_requirement: "everyone" });
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

  it("says nothing about a cost while nobody is asked", () => {
    renderPage();
    change("Second factor");

    expect(screen.queryByText("When you save")).not.toBeInTheDocument();
    expect(screen.queryByText(/personal API keys/i)).not.toBeInTheDocument();
  });

  it("offers to present a factor when the server says this account has none", () => {
    renderPage();
    change("Second factor");
    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    fireEvent.click(save());

    act(() => lastWrite?.options?.onError?.(selfUnsatisfied(), lastWrite.variables));

    expect(screen.getByText(/set up a second factor of your own/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enter a code/i })).toBeInTheDocument();
  });

  it("cannot be changed while nothing could answer it", () => {
    settings = { ...base, factor_methods_permitted: false };
    renderPage();

    // The server refuses this write; the row says so rather than offering it.
    expect(screen.getByText(/offer the authenticator app or passkeys first/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change Second factor" })).toBeNull();
  });

  describe("which providers' word counts", () => {
    it("lists the deployment's providers with the answer each one holds", () => {
      renderPage();
      change("Second factor");

      expect(screen.getByLabelText("Corp SSO")).not.toBeChecked();
      expect(screen.getByLabelText("Entra")).toBeChecked();
    });

    it("writes the same answer the provider's own page holds", async () => {
      const user = userEvent.setup();
      renderPage();
      change("Second factor");

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

  it("saves a session limit", () => {
    renderPage();
    change("Session length");

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "12" } });
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({
      session_max_hours: 12,
      session_idle_minutes: null,
    });
  });

  it("clears the limit when the field is emptied", () => {
    settings = { ...base, session_max_hours: 12 };
    renderPage();
    change("Session length");

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "" } });
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({
      session_max_hours: null,
      session_idle_minutes: null,
    });
  });

  it("will not save an unchanged or fractional limit", () => {
    settings = { ...base, session_max_hours: 12 };
    renderPage();
    change("Session length");

    expect(save()).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "1.5" } });
    expect(save()).toBeDisabled();
  });

  it("saves both halves of the answer in one write", () => {
    renderPage();
    change("Session length");

    fireEvent.change(screen.getByLabelText(/idle minutes/i), { target: { value: "20" } });
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({
      session_max_hours: null,
      session_idle_minutes: 20,
    });
  });
});

describe("breached password check", () => {
  it("turns the check off for a server that cannot reach the internet", () => {
    renderPage();
    change("Breached password check");

    fireEvent.click(screen.getByRole("radio", { name: /don't check/i }));
    fireEvent.click(save());

    // Only its own field: the other sign-in rules are left as they are.
    expect(authMutate).toHaveBeenCalledWith({ breached_password_check_enabled: false });
  });

  it("turns it back on", () => {
    settings = { ...base, breached_password_check_enabled: false };
    renderPage();
    change("Breached password check");

    fireEvent.click(
      screen.getByRole("radio", { name: "Check new passwords against known breaches" })
    );
    fireEvent.click(save());

    expect(authMutate).toHaveBeenCalledWith({ breached_password_check_enabled: true });
  });
});

describe("captcha", () => {
  it("keeps the saved secret when the field is left blank", () => {
    renderPage();
    change("Captcha");

    fireEvent.change(screen.getByLabelText(/site key/i), { target: { value: "new-site" } });
    fireEvent.click(save());

    expect(captchaMutate).toHaveBeenCalledWith({ provider: "turnstile", site_key: "new-site" });
  });

  it("sends a secret that was typed", () => {
    renderPage();
    change("Captcha");

    fireEvent.change(screen.getByLabelText(/secret key/i), { target: { value: "s3cret" } });
    fireEvent.click(save());

    expect(captchaMutate).toHaveBeenCalledWith({
      provider: "turnstile",
      site_key: "site-key",
      secret_key: "s3cret",
    });
  });

  it("says when a provider is chosen but the captcha is not on", () => {
    captcha = { ...baseCaptcha, has_secret_key: false, enforcing: false };
    renderPage();
    change("Captcha");

    expect(screen.getByText(/comes on once/i)).toBeInTheDocument();
  });
});

import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  PlatformAuthSettingsResponse,
  PlatformAuthSettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";

const requirementMutate = vi.fn();

/** The section's own error handler, as the hook received it. */
let onRequirementError:
  | ((error: unknown, variables: PlatformAuthSettingsUpdate) => void)
  | undefined;

let settings: PlatformAuthSettingsResponse;

let providers: { id: number; display_name: string; asserts_second_factor: boolean }[];
const providerMutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdatePlatformAuthSettings: (options?: {
    onError?: (error: unknown, variables: PlatformAuthSettingsUpdate) => void;
  }) => {
    onRequirementError = options?.onError;
    return { mutate: requirementMutate, isPending: false };
  },
  // The mirror beside the answer: which providers' own account of a sign-in
  // counts as presenting one.
  useAuthProviders: () => ({ data: providers, isLoading: false }),
  useUpdateAuthProvider: () => ({ mutate: providerMutate, isPending: false }),
}));

import { SecondFactorRequirementSection } from "./SecondFactorRequirementSection";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, primary: true, answers_factor: false, would_strand: 0 },
    { method: "totp", enabled: true, primary: false, answers_factor: true, would_strand: 0 },
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

// For every test in the file: the providers' tests set these too.
beforeEach(() => {
  vi.clearAllMocks();
  settings = structuredClone(base);
  providers = [
    { id: 1, display_name: "Corp SSO", asserts_second_factor: false },
    { id: 2, display_name: "Entra", asserts_second_factor: true },
  ];
});

describe("SecondFactorRequirementSection", () => {
  it("starts on the stored answer", () => {
    settings = { ...base, second_factor_requirement: "platform_roles" };
    renderWithProviders(<SecondFactorRequirementSection />);

    expect(screen.getByRole("radio", { name: /platform role/i })).toBeChecked();
  });

  it("will not save the answer that is already stored", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("saves the answer that was chosen", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(requirementMutate).toHaveBeenCalledWith({ second_factor_requirement: "everyone" });
  });

  it("says how many people the chosen answer would ask", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    fireEvent.click(screen.getByRole("radio", { name: /platform role/i }));
    expect(screen.getByText(/2 people don't have one yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));
    expect(screen.getByText(/9 people don't have one yet/i)).toBeInTheDocument();
  });

  it("says nothing about a cost while nobody is asked", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    expect(screen.queryByText(/don't have one yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/personal API keys/i)).not.toBeInTheDocument();
  });

  it("warns about the credentials that cannot present a code", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    fireEvent.click(screen.getByRole("radio", { name: /everybody/i }));

    expect(screen.getByText(/personal API keys/i)).toBeInTheDocument();
  });

  it("offers to present a factor when the server says this account has none", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    act(() => onRequirementError?.(selfUnsatisfied(), { second_factor_requirement: "everyone" }));

    expect(screen.getByText(/set up a second factor of your own/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enter a code/i })).toBeInTheDocument();
  });

  it("cannot be raised while nothing could answer it", async () => {
    settings = { ...base, factor_methods_permitted: false };
    renderWithProviders(<SecondFactorRequirementSection />);

    // The server refuses this write; the page says so rather than offering it.
    expect(
      await screen.findByText(/permit the authenticator app or passkeys first/i)
    ).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
  });
});

describe("which providers' word counts", () => {
  it("lists the deployment's providers with the answer each one holds", () => {
    renderWithProviders(<SecondFactorRequirementSection />);

    expect(screen.getByLabelText("Corp SSO")).not.toBeChecked();
    expect(screen.getByLabelText("Entra")).toBeChecked();
  });

  it("writes the same answer the provider's own page holds", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SecondFactorRequirementSection />);

    await user.click(screen.getByLabelText("Corp SSO"));

    expect(providerMutate).toHaveBeenCalledWith(
      { providerId: 1, data: { asserts_second_factor: true } },
      expect.anything()
    );
  });

  it("says nothing where the deployment has registered none", () => {
    providers = [];
    renderWithProviders(<SecondFactorRequirementSection />);

    expect(screen.queryByText(/providers whose sign-in counts/i)).not.toBeInTheDocument();
  });
});

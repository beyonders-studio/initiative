import { act, fireEvent, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  PlatformAuthSettingsResponse,
  PlatformAuthSettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";

const methodsMutate = vi.fn();

/** The section's own error handler, as the hook received it. */
let onMethodsError: ((error: unknown, variables: PlatformAuthSettingsUpdate) => void) | undefined;

let settings: PlatformAuthSettingsResponse;

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdatePlatformAuthSettings: (options?: {
    onError?: (error: unknown, variables: PlatformAuthSettingsUpdate) => void;
  }) => {
    onMethodsError = options?.onError;
    return { mutate: methodsMutate, isPending: false };
  },
}));

import { PlatformAuthSection } from "./PlatformAuthSection";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, primary: true, answers_factor: false, would_strand: 0 },
    { method: "sso", enabled: true, primary: true, answers_factor: false, would_strand: 0 },
  ],
  communities_requiring_sign_in: 0,
  factor_methods_permitted: false,
  session_max_hours: null,
  session_idle_minutes: null,
  second_factor_requirement: "nobody",
  breached_password_check_enabled: true,
  accounts_without_factor: { platform_roles: 0, everyone: 0 },
};

/** The server refusing a change and naming how many accounts it reaches. */
const refusal = (detail: string, affected: number): AxiosError => {
  const error = new AxiosError("request failed", "ERR_BAD_REQUEST");
  error.response = {
    status: 409,
    statusText: "",
    data: { detail },
    // Lowercased, as a response's header names reach the client.
    headers: new AxiosHeaders({ "x-affected-count": String(affected) }),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

const refuse = (error: AxiosError, variables: PlatformAuthSettingsUpdate) =>
  act(() => onMethodsError?.(error, variables));

describe("PlatformAuthSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    onMethodsError = undefined;
    settings = structuredClone(base);
  });

  describe("ways in", () => {
    it("sends the change without a number of its own", () => {
      settings.methods = [
        {
          method: "password",
          enabled: true,
          primary: true,
          answers_factor: false,
          would_strand: 0,
        },
        { method: "sso", enabled: true, primary: true, answers_factor: false, would_strand: 3 },
      ];
      renderWithProviders(<PlatformAuthSection />);

      fireEvent.click(screen.getByLabelText("Single sign-on"));

      expect(methodsMutate).toHaveBeenCalledWith({ methods: ["password"] });
    });

    it("asks with the number the server sent back, and acknowledges that one", () => {
      renderWithProviders(<PlatformAuthSection />);

      fireEvent.click(screen.getByLabelText("Single sign-on"));
      const change: PlatformAuthSettingsUpdate = { methods: ["password"] };
      expect(methodsMutate).toHaveBeenCalledWith(change);

      refuse(refusal("SETTINGS_LOGIN_METHODS_WOULD_STRAND", 3), change);

      expect(
        screen.getByText(/3 accounts sign in only this way and will not be able/)
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));

      expect(methodsMutate).toHaveBeenLastCalledWith({
        methods: ["password"],
        acknowledge_stranded: 3,
      });
    });

    it("asks again with the fresh number when the one it sent has moved on", () => {
      renderWithProviders(<PlatformAuthSection />);

      const change: PlatformAuthSettingsUpdate = { methods: ["password"] };
      refuse(refusal("SETTINGS_LOGIN_METHODS_STALE_ACK", 4), {
        ...change,
        acknowledge_stranded: 3,
      });

      expect(
        screen.getByText(/4 accounts sign in only this way and will not be able/)
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));

      expect(methodsMutate).toHaveBeenLastCalledWith({
        methods: ["password"],
        acknowledge_stranded: 4,
      });
    });

    it("says when communities still require a sign-in of their own", () => {
      settings.communities_requiring_sign_in = 2;
      renderWithProviders(<PlatformAuthSection />);

      expect(
        screen.getByText(/2 communities require a sign-in through a provider of their own/)
      ).toBeInTheDocument();
    });

    it("will not let the last way in be withdrawn", () => {
      settings.methods = [
        {
          method: "password",
          enabled: true,
          primary: true,
          answers_factor: false,
          would_strand: 0,
        },
        { method: "sso", enabled: false, primary: true, answers_factor: false, would_strand: 0 },
      ];
      renderWithProviders(<PlatformAuthSection />);

      expect(screen.getByLabelText("Password")).toBeDisabled();
    });
  });
});

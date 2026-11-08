import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

let settings: PlatformAuthSettingsResponse;

const lifetimeMutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdatePlatformAuthSettings: () => ({ mutate: lifetimeMutate, isPending: false }),
}));

import { SessionLifetimeSection } from "./SessionLifetimeSection";

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

describe("SessionLifetimeSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("starts blank when the deployment asks for no limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<SessionLifetimeSection />);

    expect(screen.getByLabelText(/hours/i)).toHaveValue(null);
  });

  it("saves a session limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<SessionLifetimeSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({
      session_max_hours: 12,
      session_idle_minutes: null,
    });
  });

  it("clears the limit when the field is emptied", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<SessionLifetimeSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({
      session_max_hours: null,
      session_idle_minutes: null,
    });
  });

  it("will not save an unchanged or fractional limit", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<SessionLifetimeSection />);

    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "1.5" } });
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("saves both halves of the answer in one write", async () => {
    settings = { ...base, session_max_hours: null, session_idle_minutes: null };
    renderWithProviders(<SessionLifetimeSection />);

    fireEvent.change(await screen.findByLabelText(/idle minutes/i), {
      target: { value: "20" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({
      session_max_hours: null,
      session_idle_minutes: 20,
    });
  });
});

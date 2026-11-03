import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

let settings: PlatformAuthSettingsResponse;

const checkMutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdatePlatformAuthSettings: () => ({ mutate: checkMutate, isPending: false }),
}));

import { BreachedPasswordCheckSection } from "./BreachedPasswordCheckSection";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, primary: true, answers_factor: false, would_strand: 0 },
  ],
  communities_requiring_sign_in: 0,
  factor_methods_permitted: false,
  session_max_hours: null,
  session_idle_minutes: null,
  second_factor_requirement: "nobody",
  breached_password_check_enabled: true,
  accounts_without_factor: { platform_roles: 0, everyone: 0 },
};

const toggle = () => screen.getByLabelText("Check new passwords against known breaches");

describe("BreachedPasswordCheckSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("turns the check off for a server that cannot reach the internet", () => {
    renderWithProviders(<BreachedPasswordCheckSection />);

    expect(toggle()).toBeChecked();
    fireEvent.click(toggle());

    // Only its own field: the other sign-in rules are left as they are.
    expect(checkMutate).toHaveBeenCalledWith({ breached_password_check_enabled: false });
  });

  it("turns it back on", () => {
    settings = { ...base, breached_password_check_enabled: false };
    renderWithProviders(<BreachedPasswordCheckSection />);

    expect(toggle()).not.toBeChecked();
    fireEvent.click(toggle());

    expect(checkMutate).toHaveBeenCalledWith({ breached_password_check_enabled: true });
  });
});

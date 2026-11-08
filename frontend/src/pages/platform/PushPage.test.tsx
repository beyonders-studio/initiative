import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PushSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

let settings: PushSettingsResponse;

const mutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePushSettings: () => ({ data: settings, isLoading: false, isError: false }),
  useUpdatePushSettings: () => ({ mutate, isPending: false }),
}));

import { PushPage } from "./PushPage";

const owner = buildUser({ role: "owner" });

const base: PushSettingsResponse = {
  enabled: true,
  project_id: "proj",
  application_id: "1:1:android:1",
  api_key: "key",
  sender_id: "1",
  has_service_account: true,
};

describe("PushPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("keeps the saved service account when the field is left blank", () => {
    renderWithProviders(<PushPage />, { auth: { user: owner } });

    fireEvent.change(screen.getByLabelText(/project id/i), { target: { value: "other" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(mutate).toHaveBeenCalledWith(
      {
        enabled: true,
        project_id: "other",
        application_id: "1:1:android:1",
        api_key: "key",
        sender_id: "1",
      },
      expect.anything()
    );
  });

  it("sends a pasted service account", () => {
    renderWithProviders(<PushPage />, { auth: { user: owner } });

    fireEvent.change(screen.getByLabelText(/service account/i), {
      target: { value: '{"type": "service_account"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ service_account_json: '{"type": "service_account"}' }),
      expect.anything()
    );
  });

  it("will not save a service account that is not a JSON object", () => {
    renderWithProviders(<PushPage />, { auth: { user: owner } });

    fireEvent.change(screen.getByLabelText(/service account/i), {
      target: { value: "not json" },
    });

    expect(screen.getByText(/whole key file/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });
});

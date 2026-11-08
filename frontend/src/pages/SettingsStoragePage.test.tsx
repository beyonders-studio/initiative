import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const updateMutate = vi.fn();
const testMutate = vi.fn();
const backfillMutate = vi.fn();

let storageData: Record<string, unknown> = {
  backend: "s3",
  s3_bucket: "existing-bucket",
  s3_region: "us-east-1",
  s3_endpoint_url: "https://s3.example.com",
  s3_access_key_id: "AKIA",
  has_secret_access_key: true,
  s3_use_path_style: true,
  s3_local_fallback: false,
};

vi.mock("@/hooks/useSettings", () => ({
  useStorageSettings: () => ({ data: storageData, isLoading: false, isError: false }),
  useStorageBackfillStatus: () => ({ data: { status: "idle" }, refetch: vi.fn() }),
  useUpdateStorageSettings: () => ({ mutate: updateMutate, isPending: false }),
  useTestStorageConnection: () => ({ mutate: testMutate, isPending: false }),
  useStartStorageBackfill: () => ({ mutate: backfillMutate, isPending: false }),
}));

import { SettingsStoragePage } from "./SettingsStoragePage";

const renderPage = () =>
  renderWithProviders(<SettingsStoragePage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });

describe("SettingsStoragePage", () => {
  beforeEach(() => {
    updateMutate.mockClear();
    testMutate.mockClear();
    backfillMutate.mockClear();
  });

  it("shows S3 fields prefilled from the saved config", async () => {
    renderPage();
    const bucket = (await screen.findByLabelText("Bucket")) as HTMLInputElement;
    expect(bucket.value).toBe("existing-bucket");
    // The secret field is write-only: blank with a "set" placeholder, never the value.
    const secret = screen.getByLabelText("Secret access key") as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(secret.placeholder).toMatch(/unchanged/i);
  });

  it("saves without the secret when the field is left blank (keeps stored key)", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    expect(updateMutate).toHaveBeenCalledTimes(1);
    const payload = updateMutate.mock.calls[0][0];
    expect(payload.backend).toBe("s3");
    expect(payload.s3_bucket).toBe("existing-bucket");
    expect(payload).not.toHaveProperty("s3_secret_access_key");
  });

  it("includes the secret in the payload once typed", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Secret access key"), {
      target: { value: "brand-new-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(updateMutate.mock.calls[0][0].s3_secret_access_key).toBe("brand-new-secret");
  });

  it("runs a connection test with the current form values", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(testMutate).toHaveBeenCalledTimes(1);
    expect(testMutate.mock.calls[0][0].s3_bucket).toBe("existing-bucket");
  });

  it("starts a backfill", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Start backfill" }));
    expect(backfillMutate).toHaveBeenCalledTimes(1);
  });

  it("hides S3 fields when the backend is local", async () => {
    storageData = { ...storageData, backend: "local" };
    renderPage();
    expect(await screen.findByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Bucket")).not.toBeInTheDocument();
    // Test connection is disabled for local (nothing remote to reach).
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled();
    // The backfill copies into the saved bucket, which local has not got.
    expect(screen.getByRole("button", { name: "Start backfill" })).toBeDisabled();
    storageData = { ...storageData, backend: "s3" }; // restore for other tests
  });
});

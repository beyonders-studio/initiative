import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { RegistryStatusRead } from "@/api/generated/initiativeAPI.schemas";

let status: Partial<RegistryStatusRead> = {};
const updateMutate = vi.fn();
const refreshMutate = vi.fn();
const uploadMutate = vi.fn();

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/generated/marketplace/marketplace", () => ({
  useReadRegistryStatus: () => ({ data: status }),
}));

vi.mock("@/hooks/useMarketplaceRegistry", () => ({
  useUpdateRegistrySettings: () => ({ mutate: updateMutate, isPending: false }),
  useRefreshRegistry: () => ({ mutate: refreshMutate, isPending: false }),
  useUploadRegistryBundle: () => ({ mutate: uploadMutate, isPending: false }),
}));

import { MarketplaceRegistrySection } from "./MarketplaceRegistrySection";

const following = (overrides: Partial<RegistryStatusRead> = {}) => ({
  enabled: true,
  configured: true,
  custom_root: false,
  registry_url: "https://packages.example.com/cloud/",
  expires_at: null,
  last_success_at: "2026-11-18T13:16:00Z",
  last_source: "registry",
  last_error: null,
  listing_count: 4,
  ...overrides,
});

describe("MarketplaceRegistrySection", () => {
  beforeEach(() => {
    updateMutate.mockReset();
    refreshMutate.mockReset();
    uploadMutate.mockReset();
  });

  it("keeps a server getting updates to one row, with Refresh now beside the switch", async () => {
    const user = userEvent.setup();
    status = following();
    renderWithProviders(<MarketplaceRegistrySection />);

    expect(screen.getByText("Plug-in registry")).toBeInTheDocument();
    expect(screen.getByText(/4 listings/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Get updates from the registry" })).toBeChecked();
    // Nothing to upload while the registry itself is followed, and no address.
    expect(screen.queryByText(/registry bundle/)).toBeNull();
    expect(screen.queryByText(/packages\.example\.com/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Refresh now" }));
    expect(refreshMutate).toHaveBeenCalled();
  });

  it("offers a bundle in place of Refresh once updates are off, and applies it on drop", () => {
    status = following({ enabled: false, last_source: "bundle" });
    renderWithProviders(<MarketplaceRegistrySection />);

    expect(screen.queryByRole("button", { name: "Refresh now" })).toBeNull();
    expect(screen.getByText(/To update a server without internet access/)).toBeInTheDocument();
    expect(screen.getByText(/from a bundle · 4 listings/)).toBeInTheDocument();

    // Dropped, it applies at once: there is no second button to press.
    const bundle = new File(["x"], "registry.tar.gz", { type: "application/gzip" });
    const area = screen.getByText("Drop a registry bundle (.tar.gz)").parentElement as HTMLElement;
    fireEvent.drop(area, { dataTransfer: { types: ["Files"], files: [bundle] } });
    expect(uploadMutate).toHaveBeenCalledWith(bundle);
    expect(screen.queryByRole("button", { name: "Upload bundle" })).toBeNull();
  });

  it("says why the last update stopped, only while it did", () => {
    status = following({ last_error: "REGISTRY_UNREACHABLE" });
    renderWithProviders(<MarketplaceRegistrySection />);

    expect(screen.getByText(/The last attempt stopped/)).toBeInTheDocument();
  });
});

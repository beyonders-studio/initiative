import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  RegistryRefreshRead,
  RegistrySkippedListing,
  RegistryStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { toast } from "@/lib/mascotToast";

const VERSION_REUSED = "MARKETPLACE_REGISTRY_VERSION_REUSED";
const REUSED_TEXT =
  "This version is already on this server with different content. A published version can't change, so its publisher has to publish the change as a new version.";

const buildStatus = (overrides: Partial<RegistryStatusRead> = {}): RegistryStatusRead => ({
  enabled: true,
  configured: true,
  custom_root: false,
  registry_url: "https://packages.example.com",
  root_version: 1,
  expires_at: null,
  last_source: "https://packages.example.com",
  last_attempt_at: "2026-11-18T19:21:57.000Z",
  last_success_at: "2026-11-18T02:00:00.000Z",
  last_error: null,
  listing_count: 3,
  skipped: [],
  ...overrides,
});

const skip = (overrides: Partial<RegistrySkippedListing>): RegistrySkippedListing => ({
  name: "publishers/beyonders-studio/TSJVTCM0S7GV2X/listing.json",
  code: VERSION_REUSED,
  listing_name: null,
  publisher_name: null,
  ...overrides,
});

// Flipped per test before rendering; read lazily inside the mocked hooks.
let status: RegistryStatusRead = buildStatus();
let refreshResult: RegistryRefreshRead;
const uploadMutate = vi.fn();

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/generated/marketplace/marketplace", () => ({
  useReadRegistryStatus: () => ({ data: status }),
}));

vi.mock("@/hooks/useMarketplaceRegistry", () => ({
  useUpdateRegistrySettings: () => ({ mutate: vi.fn(), isPending: false }),
  useUploadRegistryBundle: () => ({ mutate: uploadMutate, isPending: false }),
  useRefreshRegistry: (options?: { onSuccess?: (result: RegistryRefreshRead) => void }) => ({
    mutate: () => options?.onSuccess?.(refreshResult),
    isPending: false,
  }),
}));

import { MarketplaceRegistrySection } from "./MarketplaceRegistrySection";

const render = () =>
  renderWithProviders(<MarketplaceRegistrySection />, {
    auth: { user: buildUser({ role: "owner", capabilities: ["config.manage"] }) },
  });

const refreshing = (skipped: RegistrySkippedListing[]): RegistryRefreshRead => ({
  root_version: 1,
  upserted: 2,
  withdrawn: 0,
  unchanged: false,
  skipped,
});

describe("MarketplaceRegistrySection", () => {
  beforeEach(() => {
    status = buildStatus();
    vi.mocked(toast.warning).mockReset();
    uploadMutate.mockReset();
  });

  it("keeps a server getting updates to one row, with Refresh now beside the switch", () => {
    render();

    expect(screen.getByText("Plug-in registry")).toBeInTheDocument();
    expect(screen.getByText(/3 listings/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Get updates from the registry" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Refresh now" })).toBeInTheDocument();
    // Nothing to upload while the registry itself is followed, and no address.
    expect(screen.queryByText(/registry bundle/)).toBeNull();
    expect(screen.queryByText(/packages\.example\.com/)).toBeNull();
  });

  it("offers a bundle in place of Refresh once updates are off, and applies it on drop", () => {
    status = buildStatus({ enabled: false, last_source: "bundle" });
    render();

    expect(screen.queryByRole("button", { name: "Refresh now" })).toBeNull();
    expect(screen.getByText(/To update a server without internet access/)).toBeInTheDocument();
    expect(screen.getByText(/from a bundle · 3 listings/)).toBeInTheDocument();

    // Dropped, it applies at once: there is no second button to press.
    const bundle = new File(["x"], "registry.tar.gz", { type: "application/gzip" });
    const area = screen.getByText("Drop a registry bundle (.tar.gz)").parentElement as HTMLElement;
    fireEvent.drop(area, { dataTransfer: { types: ["Files"], files: [bundle] } });
    expect(uploadMutate).toHaveBeenCalledWith(bundle);
    expect(screen.queryByRole("button", { name: "Upload bundle" })).toBeNull();
  });

  // One skipped listing is named in the toast with why; several are named together.
  it.each([
    [[skip({ listing_name: "Demo" })], `Demo was skipped. ${REUSED_TEXT}`],
    [
      [
        skip({ listing_name: "Demo" }),
        skip({ code: "MARKETPLACE_REGISTRY_TARGET_REJECTED", listing_name: "GitHub" }),
      ],
      "Skipped: Demo, GitHub. The status below says why.",
    ],
  ])("names what a refresh skipped in the toast (%#)", async (skipped, said) => {
    refreshResult = refreshing(skipped);
    render();

    await userEvent.click(screen.getByRole("button", { name: "Refresh now" }));

    expect(toast.warning).toHaveBeenCalledWith(said);
  });

  it("lists what the last update skipped and why, by name", async () => {
    status = buildStatus({
      last_error: VERSION_REUSED,
      skipped: [
        skip({ listing_name: "Demo" }),
        skip({ code: "MARKETPLACE_REGISTRY_EXPIRED", publisher_name: "Acme" }),
        skip({ code: "MARKETPLACE_REGISTRY_TERMS_INVALID" }),
      ],
    });
    render();

    expect(await screen.findByText("Skipped in the last update:")).toBeInTheDocument();
    expect(screen.getByText(`Demo: ${REUSED_TEXT}`)).toBeInTheDocument();
    expect(screen.getByText(/^Listings from Acme: /)).toBeInTheDocument();
    expect(screen.getByText(/^Part of the registry: /)).toBeInTheDocument();
    // The skips say it; the first one's code is not repeated as a stop.
    expect(screen.queryByText(/The last attempt stopped/)).toBeNull();
  });

  it("still says why a refresh that stopped did", async () => {
    status = buildStatus({ last_error: "MARKETPLACE_REGISTRY_UNREACHABLE" });
    render();

    expect(await screen.findByText(/^The last attempt stopped: /)).toBeInTheDocument();
  });
});

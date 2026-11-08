import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { useCommunities } from "@/hooks/useCommunities";

import { CommunityExportCard } from "./CommunityExportCard";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/exportDownload", () => ({
  downloadExportArtifact: vi.fn(),
}));

const activeCommunity = buildCommunity({ id: 1, name: "Test Community", role: "superadmin" });
const communitiesValue: ReturnType<typeof useCommunities> = {
  communities: [activeCommunity],
  activeCommunityId: 1,
  activeCommunity,
  activeCommunityReadOnly: false,
  loading: false,
  error: null,
  refreshCommunities: vi.fn(),
  switchCommunity: vi.fn(),
  syncCommunityFromUrl: vi.fn(),
  createCommunity: vi.fn(),
  updateCommunityInState: vi.fn(),
  reorderCommunities: vi.fn(),
  canCreateCommunities: true,
};

// Taking the whole community out in one file is the seat's errand, and the
// card says so itself rather than resting on which tab it sits in. Partial:
// the render helper reaches for ``CommunityContext`` from this module.
vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () => communitiesValue,
}));

const now = new Date();
const iso = (offsetMs: number) => new Date(now.getTime() + offsetMs).toISOString();

const job = (o: Record<string, unknown> = {}) => ({
  id: 7,
  community_id: 1,
  created_by: 1,
  source: "community",
  template_id: "backup",
  format: "zip",
  params: {},
  status: "done",
  error: null,
  delivered: false,
  expires_at: iso(6 * 86_400_000),
  created_at: iso(-3_600_000),
  updated_at: iso(-3_600_000),
  ...o,
});

const status = (o: Record<string, unknown> = {}) =>
  communityHttp.get("/exports/community/status", () =>
    HttpResponse.json({
      cooldown_hours: 48,
      next_available_at: null,
      latest: null,
      latest_started_by: null,
      ...o,
    })
  );

describe("CommunityExportCard", () => {
  it("names who took the last export and offers it back", async () => {
    server.use(status({ latest: job(), latest_started_by: "Ada Lovelace" }));
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/Ada Lovelace/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
    expect(screen.getByText(/download expires/i)).toBeInTheDocument();
  });

  it("holds the door shut while the community is inside its cooldown", async () => {
    server.use(
      status({
        latest: job({ status: "queued", expires_at: null }),
        latest_started_by: "Ada Lovelace",
        next_available_at: iso(2 * 86_400_000),
      })
    );
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/next export available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled();
    // A queued job has nothing to hand back yet.
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });

  it("says so when nobody has taken one", async () => {
    server.use(status());
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/nobody has exported this community yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeEnabled();
  });
});

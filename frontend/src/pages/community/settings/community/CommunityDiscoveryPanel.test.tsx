/**
 * Opting a community into the community directory.
 *
 * Listing publishes a community to everyone signed in, so the interesting cases are
 * all about what has to be true first: at least one category, an explicit
 * certification that the community is free of adult content, and room for somebody
 * to actually join. The server enforces all three; what is checked here is that
 * the UI asks before the request rather than reporting after it.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";

import { CommunityDiscoveryPanel } from "./CommunityDiscoveryPanel";

const patchCommunity = vi.fn();

// Listing is offered only where the platform owner runs a directory; the tests
// below are about a deployment that does, except the one that says otherwise.
const config = vi.hoisted(() => ({ communityDirectory: true }));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ communityDirectoryEnabled: config.communityDirectory }),
}));

vi.mock("@/api/generated/communities/communities", () => ({
  updateCommunity: (...args: unknown[]) => patchCommunity(...args),
}));

const renderPanel = (community: CommunityRead) =>
  renderWithProviders(<CommunityDiscoveryPanel />, {
    communities: {
      communities: [community],
      activeCommunityId: community.id,
      activeCommunity: community,
      loading: false,
      error: null,
      refreshCommunities: vi.fn(),
      switchCommunity: vi.fn(),
      syncCommunityFromUrl: vi.fn(),
      createCommunity: vi.fn(),
      updateCommunityInState: vi.fn(),
      reorderCommunities: vi.fn(),
      canCreateCommunities: true,
    },
  });

const adminCommunity = (overrides: Partial<CommunityRead> = {}) =>
  buildCommunity({ id: 7, role: "admin", ...overrides });

const listingToggle = () => screen.getByLabelText("List this community");
const dialog = () => screen.getByRole("dialog");
const certify = () => within(dialog()).getByLabelText("This community contains no adult content");

beforeEach(() => {
  vi.clearAllMocks();
  config.communityDirectory = true;
  patchCommunity.mockResolvedValue(adminCommunity({ is_community: true }));
});

describe("CommunityDiscoveryPanel", () => {
  it("is absent where the platform owner runs no directory", () => {
    config.communityDirectory = false;
    renderPanel(adminCommunity());

    expect(screen.queryByLabelText("List this community")).not.toBeInTheDocument();
  });

  it("is absent for a member", () => {
    renderPanel(buildCommunity({ id: 7, role: "member" }));

    expect(screen.queryByText("Community directory")).not.toBeInTheDocument();
  });

  it("offers the opt-in to a community admin", () => {
    renderPanel(adminCommunity());

    expect(screen.getByText("Community directory")).toBeInTheDocument();
    expect(listingToggle()).not.toBeChecked();
  });

  describe("the publish dialog", () => {
    it("stands between the toggle and the listing", async () => {
      renderPanel(adminCommunity());

      await userEvent.click(listingToggle());

      expect(await screen.findByRole("dialog")).toBeInTheDocument();
      // Nothing is published by opening it.
      expect(patchCommunity).not.toHaveBeenCalled();
    });

    it("will not confirm without a category", async () => {
      renderPanel(adminCommunity());
      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");

      await userEvent.click(certify());

      expect(within(dialog()).getByRole("button", { name: "List this community" })).toBeDisabled();
    });

    it("will not confirm without the certification", async () => {
      renderPanel(adminCommunity());
      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");

      await userEvent.click(within(dialog()).getByRole("button", { name: "Gaming" }));

      expect(within(dialog()).getByRole("button", { name: "List this community" })).toBeDisabled();
    });

    it("spells out what the certification covers", async () => {
      renderPanel(adminCommunity());
      await userEvent.click(listingToggle());
      const panel = await screen.findByRole("dialog");

      // The criminal-liability line especially must be stated, not implied.
      expect(within(panel).getByText("Any sexual content involving a minor")).toBeInTheDocument();
      expect(within(panel).getByText("Pornography, sexual content, or nudity")).toBeInTheDocument();
      expect(within(panel).getByText(/Illegal activity — drug use or sale/)).toBeInTheDocument();
      expect(within(panel).getByText(/you are expected to watch for/i)).toBeInTheDocument();
    });

    it("publishes with the categories picked and the 18+ question answered", async () => {
      renderPanel(adminCommunity());
      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");

      await userEvent.click(within(dialog()).getByRole("button", { name: "Gaming" }));
      await userEvent.click(within(dialog()).getByRole("button", { name: "Tabletop RPG" }));
      await userEvent.click(certify());
      await userEvent.click(within(dialog()).getByRole("button", { name: "List this community" }));

      await waitFor(() => {
        expect(patchCommunity).toHaveBeenCalledWith(7, {
          is_community: true,
          categories: ["gaming", "ttrpg"],
          has_adult_content: false,
        });
      });
    });

    it("asks for the certification again every time it opens", async () => {
      renderPanel(adminCommunity());

      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");
      await userEvent.click(certify());
      await userEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));

      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");
      expect(certify()).not.toBeChecked();
    });
  });

  /** A listing is a front door; the prompt is about the room behind it. */
  describe("the auto-join prompt", () => {
    it("is absent while the community is not listed", () => {
      renderPanel(adminCommunity());

      expect(
        screen.queryByText("New members will arrive to an empty community")
      ).not.toBeInTheDocument();
    });

    it("warns a listed community that has nothing to land people in", async () => {
      // The default handler's initiative carries no auto-join.
      renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

      expect(
        await screen.findByText("New members will arrive to an empty community")
      ).toBeInTheDocument();
    });

    it("is gone once an initiative takes new members", async () => {
      server.use(
        communityHttp.get("/initiatives/", () =>
          HttpResponse.json([
            buildInitiative({ name: "Welcome", join_policy: "open", auto_join: true }),
          ])
        )
      );

      renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

      await waitFor(() =>
        expect(
          screen.queryByText("New members will arrive to an empty community")
        ).not.toBeInTheDocument()
      );
    });
  });

  it("un-lists on the click, with nothing to confirm", async () => {
    renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

    await userEvent.click(listingToggle());

    await waitFor(() => {
      expect(patchCommunity).toHaveBeenCalledWith(7, { is_community: false });
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("edits the shelves of an already-listed community in place", async () => {
    renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

    await userEvent.click(screen.getByRole("button", { name: "Gaming" }));

    await waitFor(() => {
      expect(patchCommunity).toHaveBeenCalledWith(7, { categories: ["art", "gaming"] });
    });
  });

  describe("the carve-outs", () => {
    it("does not offer the toggle to a community with room for one", async () => {
      renderPanel(adminCommunity({ max_users: 1 }));

      expect(listingToggle()).toBeDisabled();
      expect(screen.getByText(/room for only one person/)).toBeInTheDocument();
    });

    it("offers it once there is room for two", () => {
      renderPanel(adminCommunity({ max_users: 2 }));

      expect(listingToggle()).toBeEnabled();
    });
  });

  /** The 18+ question belongs to the directory, so the panel never puts it to a
   *  community outside one — the certification in the dialog is where it is asked. */
  describe("the 18+ question", () => {
    it("is not put to a community that keeps to itself", () => {
      renderPanel(adminCommunity());

      expect(screen.queryByText(/adult content \(18\+\)/)).not.toBeInTheDocument();
    });

    it("is not put to a listed community either", () => {
      renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

      expect(screen.queryByText(/adult content \(18\+\)/)).not.toBeInTheDocument();
    });

    it("still offers the listing to a community that had declared itself 18+", async () => {
      renderPanel(adminCommunity({ has_adult_content: true }));

      expect(listingToggle()).toBeEnabled();

      await userEvent.click(listingToggle());
      await screen.findByRole("dialog");
      await userEvent.click(within(dialog()).getByRole("button", { name: "Gaming" }));
      await userEvent.click(certify());
      await userEvent.click(within(dialog()).getByRole("button", { name: "List this community" }));

      // The certification answers the question afresh, whatever it said before.
      await waitFor(() => {
        expect(patchCommunity).toHaveBeenCalledWith(7, {
          is_community: true,
          categories: ["gaming"],
          has_adult_content: false,
        });
      });
    });
  });

  it("reports a refused save rather than looking like it worked", async () => {
    patchCommunity.mockRejectedValue(new Error("nope"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPanel(adminCommunity({ is_community: true, categories: ["art"] }));

    await userEvent.click(screen.getByRole("button", { name: "Gaming" }));

    expect(await screen.findByText("Unable to update community.")).toBeInTheDocument();
  });
});

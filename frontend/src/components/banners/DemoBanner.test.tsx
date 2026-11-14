/**
 * The top bar's first row: a demo visitor sees their copy and how long it has
 * left there, a pitch's admins on the demo server see its Publish banner, and
 * every other account keeps the recents tabs.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityRole } from "@/api/generated/initiativeAPI.schemas";
import { toast } from "@/lib/mascotToast";

import { DemoBannerOrTabs } from "./DemoBanner";

vi.mock("@/lib/mascotToast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PITCH = "/api/v1/c/:communityId/demo/pitch";

/** The server's bootstrap answer, saying whether it is the demo. */
const onServer = (demo: boolean) => {
  const asked = vi.fn();
  server.use(
    http.get("/api/v1/auth/bootstrap", () => {
      asked();
      return HttpResponse.json({ has_users: true, public_registration_enabled: true, demo });
    })
  );
  return asked;
};

/** Signed in to a community, at `role`, that the pitch handler answers for. */
const inCommunity = (role: CommunityRole) => {
  const community = buildCommunity({ id: 3, role });
  return {
    auth: { user: buildUser({ demo_expires_at: null }) },
    communities: { communities: [community], activeCommunityId: 3, activeCommunity: community },
  };
};

const TopRow = () => (
  <DemoBannerOrTabs>
    <p>recent tabs</p>
  </DemoBannerOrTabs>
);

const mount = async (options: Parameters<typeof renderPage>[1]) => {
  const result = renderPage(TopRow, options);
  await waitFor(() => expect(result.router.state.status).toBe("idle"));
  return result;
};

describe("DemoBannerOrTabs", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a demo account its copy and the time left, in place of the tabs", async () => {
    // A little under 3 h 12 m, so the minutes round up to 12.
    const expiresAt = new Date(Date.now() + (192 * 60 - 20) * 1000).toISOString();
    await mount({
      auth: { user: buildUser({ demo_expires_at: expiresAt, demo_community_id: 4 }) },
      communities: {
        communities: [
          buildCommunity({ name: "Elsewhere" }),
          buildCommunity({ id: 4, name: "Rosie's Bakery" }),
        ],
      },
    });

    expect(
      await screen.findByText("This is a demo copy of Rosie's Bakery. It's deleted in 3h 12m.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Visit the main site" })).toHaveAttribute(
      "href",
      "/welcome"
    );
    expect(screen.queryByText("recent tabs")).not.toBeInTheDocument();
  });

  it("keeps the tabs for an account without a copy", async () => {
    await mount({ auth: { user: buildUser({ demo_expires_at: null }) } });

    expect(await screen.findByText("recent tabs")).toBeInTheDocument();
    expect(screen.queryByText(/demo copy/)).not.toBeInTheDocument();
  });

  it("takes an email for a follow-up from a demo account, and thanks them", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post("/api/v1/demo/lead", async ({ request }) => {
        sent.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      })
    );
    const expiresAt = new Date(Date.now() + 60 * 60_000).toISOString();
    await mount({
      auth: { user: buildUser({ demo_expires_at: expiresAt, demo_community_id: 1 }) },
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Leave your email" }));
    expect(screen.getByText("Liked what you saw?")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "pat@example.com");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Thanks. Someone will be in touch soon.")).toBeInTheDocument();
    expect(sent).toEqual([{ email: "pat@example.com" }]);
  });

  it("shows a pitch's admin when visitors' version was published, and publishes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    onServer(true);
    const read = vi.fn();
    const published = vi.fn();
    let lastPublishedAt = new Date(Date.now() - 5 * 60_000).toISOString();
    server.use(
      http.get(PITCH, ({ params }) => {
        read(params.communityId);
        return HttpResponse.json({ is_pitch: true, last_published_at: lastPublishedAt });
      }),
      http.post("/api/v1/c/:communityId/demo/publish", ({ params }) => {
        published(params.communityId);
        return new HttpResponse(null, { status: 202 });
      })
    );
    await mount(inCommunity("admin"));

    expect(
      await screen.findByText("Visitors get the version you last published 5 minutes ago.")
    ).toBeInTheDocument();
    expect(screen.queryByText("recent tabs")).not.toBeInTheDocument();

    await userEvent
      .setup({ advanceTimers: vi.advanceTimersByTime })
      .click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(published).toHaveBeenCalledWith("3"));
    expect(toast.success).toHaveBeenCalledWith(
      "Publishing now. Visitors get this version once it's ready."
    );

    // The export is queued: the pitch is read again until its time moves.
    await vi.advanceTimersByTimeAsync(2_000);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/5 minutes ago/)).toBeInTheDocument();

    lastPublishedAt = new Date(Date.now() - 60_000).toISOString();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(
      await screen.findByText("Visitors get the version you last published 1 minute ago.")
    ).toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(3);

    // And then it stops asking.
    await vi.advanceTimersByTimeAsync(6_000);
    expect(read).toHaveBeenCalledTimes(3);
  });

  it("keeps the tabs for a pitch's members", async () => {
    onServer(true);
    const read = vi.fn();
    server.use(
      http.get(PITCH, () => {
        read();
        return HttpResponse.json({ is_pitch: true, last_published_at: null });
      })
    );
    await mount(inCommunity("member"));

    expect(await screen.findByText("recent tabs")).toBeInTheDocument();
    expect(read).not.toHaveBeenCalled();
  });

  it("asks nothing about pitches on a server that is not the demo", async () => {
    const bootstrap = onServer(false);
    const read = vi.fn();
    server.use(
      http.get(PITCH, () => {
        read();
        return HttpResponse.json({ is_pitch: true, last_published_at: null });
      })
    );
    await mount(inCommunity("admin"));

    await waitFor(() => expect(bootstrap).toHaveBeenCalled());
    expect(await screen.findByText("recent tabs")).toBeInTheDocument();
    expect(read).not.toHaveBeenCalled();
  });
});

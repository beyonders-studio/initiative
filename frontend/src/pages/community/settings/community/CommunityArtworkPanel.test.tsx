import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildBanner, buildCommunity } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { CommunityArtworkPanel } from "./CommunityArtworkPanel";

const entitlements = (bannerImageEnabled: boolean) =>
  server.use(
    http.get("*/api/v1/communities/:communityId/entitlements", () =>
      HttpResponse.json({ community_id: 1, banner_image_enabled: bannerImageEnabled })
    )
  );

describe("CommunityArtworkPanel", () => {
  it("offers a banner upload where the community has artwork on its plan", async () => {
    entitlements(true);

    renderWithProviders(
      <CommunityArtworkPanel community={buildCommunity({ id: 1, role: "admin" })} />
    );

    expect(await screen.findByLabelText("Banner")).toBeInTheDocument();
  });

  it("offers the colour alone where it does not", async () => {
    entitlements(false);

    renderWithProviders(
      <CommunityArtworkPanel community={buildCommunity({ id: 1, role: "admin" })} />
    );

    await waitFor(() =>
      expect(screen.getByText(/plan doesn't include banner images/i)).toBeInTheDocument()
    );
    // The label stays — the banner still exists as a thing this community has.
    expect(screen.queryByLabelText("Banner")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Banner fill")).toBeInTheDocument();
  });

  it("keeps showing a banner the community already had", async () => {
    entitlements(false);

    const { container } = renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({
          id: 1,
          role: "admin",
          banner: buildBanner({ image_url: "/api/v1/communities/1/image/abc" }),
        })}
      />
    );

    await waitFor(() =>
      expect(container.querySelector('img[src="/api/v1/communities/1/image/abc"]')).not.toBeNull()
    );
    expect(screen.getByRole("button", { name: "Remove banner" })).toBeInTheDocument();
  });

  it("previews the banner once, showing the fill where there is no artwork", async () => {
    entitlements(true);

    const { container } = renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({
          id: 1,
          role: "admin",
          name: "Ravenloft",
          banner: buildBanner({ color: "#2a9d8f" }),
        })}
      />
    );

    await screen.findByLabelText("Banner fill");
    // One preview, not one per control — the community is named once, on the fill.
    const name = screen.getByText("Ravenloft");
    expect(container.querySelectorAll("img")).toHaveLength(0);
    // The fill is a layer under the name rather than the name's own box, so a
    // fade can be shown on it without dimming the words.
    expect(name.previousElementSibling).toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("saves a text colour the moment it is chosen, with no confirm step", async () => {
    entitlements(true);
    const patched: unknown[] = [];
    server.use(
      http.patch("*/api/v1/communities/:communityId", async ({ request }) => {
        const body = await request.json();
        patched.push(body);
        return HttpResponse.json(
          buildCommunity({
            id: 1,
            role: "admin",
            name: "Ravenloft",
            banner: buildBanner({ text_color: "#000000" }),
          })
        );
      })
    );

    renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({ id: 1, role: "admin", name: "Ravenloft" })}
      />
    );

    await userEvent.click(await screen.findByRole("button", { name: "Dark" }));

    // The preview answers immediately...
    expect(screen.getByText("Ravenloft")).toHaveStyle({ color: "rgb(0, 0, 0)" });
    // ...and so does the server, without anyone pressing anything else.
    await waitFor(() => expect(patched).toHaveLength(1));
    // The whole banner rides in the body, since that is what it is.
    expect(patched[0]).toMatchObject({
      banner: { color: "#2563eb", text_color: "#000000", text_align: "center", fade: "strong" },
    });
    expect(screen.queryByRole("button", { name: /use this colour/i })).not.toBeInTheDocument();
  });

  it("offers banner text as two colours, never a picker", async () => {
    entitlements(true);

    renderWithProviders(
      <CommunityArtworkPanel community={buildCommunity({ id: 1, role: "admin" })} />
    );

    // Black or white only: a fill the community picked, or artwork of any colour,
    // stays readable only at one end of the scale or the other.
    expect(await screen.findByRole("button", { name: "Light" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByLabelText("Banner text")).not.toBeInTheDocument();
  });

  it("always offers the icon — it is not part of that entitlement", async () => {
    entitlements(false);

    renderWithProviders(
      <CommunityArtworkPanel community={buildCommunity({ id: 1, role: "admin" })} />
    );

    expect(await screen.findByLabelText("Icon")).toBeInTheDocument();
  });

  it("saves the alignment the moment it is picked, with the fade beside it", async () => {
    entitlements(true);
    const patched: Record<string, unknown>[] = [];
    server.use(
      http.patch("*/api/v1/communities/:communityId", async ({ request }) => {
        patched.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          buildCommunity({
            id: 1,
            role: "admin",
            name: "Ravenloft",
            banner: buildBanner({ text_align: "left" }),
          })
        );
      })
    );

    renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({
          id: 1,
          role: "admin",
          name: "Ravenloft",
          banner: buildBanner({ fade: "weak" }),
        })}
      />
    );

    await userEvent.click(await screen.findByRole("button", { name: "Left" }));

    await waitFor(() => expect(patched).toHaveLength(1));
    // The whole banner rides together, so a PATCH carries the community's own fade
    // rather than resetting the part the admin did not touch.
    expect(patched[0]).toMatchObject({ banner: { text_align: "left", fade: "weak" } });
  });

  it("offers three fades, with the community's own already pressed", async () => {
    entitlements(true);

    renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({ id: 1, role: "admin", banner: buildBanner({ fade: "weak" }) })}
      />
    );

    expect(await screen.findByRole("button", { name: "Soft" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "None" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Strong" })).toHaveAttribute("aria-pressed", "false");
  });

  it("puts the layout back along with the colours on a reset", async () => {
    entitlements(true);
    const patched: Record<string, unknown>[] = [];
    server.use(
      http.patch("*/api/v1/communities/:communityId", async ({ request }) => {
        patched.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(buildCommunity({ id: 1, role: "admin" }));
      })
    );

    renderWithProviders(
      <CommunityArtworkPanel
        community={buildCommunity({
          id: 1,
          role: "admin",
          banner: buildBanner({ fade: "strong", text_align: "left" }),
        })}
      />
    );

    await userEvent.click(await screen.findByRole("button", { name: "Reset to default" }));

    // Null is a reset, not a removal — a banner is never without a layout.
    await waitFor(() => expect(patched).toHaveLength(1));
    expect(patched[0]).toEqual({ banner: null });
  });
});

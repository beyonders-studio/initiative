/**
 * Sign in with Initiative's page: what a person sent here by a plug-in sees
 * signed out, the places they choose between signed in, and the offer to add
 * the plug-in when there is nowhere to open it yet.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { PluginSignInPage } from "./PluginSignInPage";

const REQUEST = {
  response_type: "code",
  client_id: "acme.hoard",
  redirect_uri: "https://hoard.example.test/signed-in",
  scope: "openid",
  state: "s",
  nonce: "n",
  code_challenge: "c".repeat(43),
  code_challenge_method: "S256",
};
const PAGE = { initialRoute: "/oauth/authorize", routerSearch: REQUEST };

const CLIENT = {
  name: "Hoard",
  listing_public_id: "acme.hoard",
  refusal_redirect: null,
  cancel_redirect: "https://hoard.example.test/signed-in?error=access_denied&state=s",
};

const place = (community_id: number, initiative_id: number | null = null) => ({
  community_id,
  community_name: `Community ${community_id}`,
  initiative_id,
  initiative_name: initiative_id ? `Initiative ${initiative_id}` : null,
});

let assign: ReturnType<typeof vi.fn>;
let authorized: unknown[];

beforeEach(() => {
  assign = vi.fn();
  authorized = [];
  vi.stubGlobal("location", { ...window.location, assign, replace: vi.fn() });
  server.use(
    http.get("/api/v1/plugin-platform/oauth/authorize/client", () => HttpResponse.json(CLIENT)),
    http.post("/api/v1/plugin-platform/oauth/authorize", async ({ request }) => {
      authorized.push(await request.json());
      return HttpResponse.json({ redirect_to: "https://hoard.example.test/signed-in?code=x" });
    })
  );
});

afterEach(() => vi.unstubAllGlobals());

const places = (body: { places: unknown[]; installed_community_ids: number[] }) =>
  server.use(
    http.get("/api/v1/plugin-platform/oauth/authorize/places", () => HttpResponse.json(body))
  );

describe("PluginSignInPage", () => {
  it("offers Initiative's own sign-in and sign-up, each coming back here", async () => {
    renderPage(PluginSignInPage, { ...PAGE, auth: { user: null, loading: false } });

    expect(await screen.findByText("Sign in to continue to Hoard")).toBeInTheDocument();
    const signIn = screen.getByRole("link", { name: "Sign in" });
    const signUp = screen.getByRole("link", { name: "Create an account" });
    for (const link of [signIn, signUp]) {
      const next = new URL(link.getAttribute("href") ?? "", "http://x").searchParams.get("next");
      expect(next).toContain("/oauth/authorize?");
      expect(next).toContain("client_id=acme.hoard");
    }
  });

  it("says why a request that cannot continue stops here", async () => {
    server.use(
      http.get("/api/v1/plugin-platform/oauth/authorize/client", () =>
        HttpResponse.json({ detail: "PLUGIN_SIGN_IN_REDIRECT_MISMATCH" }, { status: 400 })
      )
    );
    renderPage(PluginSignInPage, { ...PAGE, auth: { user: buildUser(), loading: false } });

    expect(await screen.findByText(/asked to return somewhere/i)).toBeInTheDocument();
  });

  it("sends the person back with a code for the place they choose", async () => {
    const user = userEvent.setup();
    places({ places: [place(1), place(1, 7)], installed_community_ids: [1] });
    renderPage(PluginSignInPage, { ...PAGE, auth: { user: buildUser(), loading: false } });

    await user.click(await screen.findByRole("button", { name: "Initiative 7 in Community 1" }));

    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(assign).toHaveBeenCalledWith("https://hoard.example.test/signed-in?code=x");
    expect(authorized).toEqual([{ ...REQUEST, community_id: 1, initiative_id: 7 }]);
  });

  it("goes straight on when there is one place", async () => {
    places({ places: [place(1)], installed_community_ids: [1] });
    renderPage(PluginSignInPage, { ...PAGE, auth: { user: buildUser(), loading: false } });

    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(authorized).toEqual([{ ...REQUEST, community_id: 1, initiative_id: null }]);
  });

  it("offers to add the plug-in where the person runs a community, or to start one", async () => {
    places({ places: [], installed_community_ids: [] });
    const runs = buildCommunity({ role: "superadmin", name: "Bakery" });
    renderPage(PluginSignInPage, {
      ...PAGE,
      auth: { user: buildUser(), loading: false },
      communities: { communities: [runs], canCreateCommunities: true },
    });

    expect(await screen.findByRole("button", { name: "Add Hoard to Bakery" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start a community with Hoard" })
    ).toBeInTheDocument();
    expect(authorized).toEqual([]);
  });

  it("says a failed read failed, rather than that the plug-in is missing", async () => {
    server.use(
      http.get("/api/v1/plugin-platform/oauth/authorize/places", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    );
    renderPage(PluginSignInPage, {
      ...PAGE,
      auth: { user: buildUser(), loading: false },
      communities: {
        communities: [buildCommunity({ role: "superadmin" })],
        canCreateCommunities: true,
      },
    });

    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Add Hoard/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start a community/ })).not.toBeInTheDocument();
  });
});

/**
 * A demo link, `/demo#<token>`, through the router the app ships: the page
 * takes the token out of the address, trades it for a signed-in copy, waits
 * for the copy to be filled and lands there; a visitor whose copy is still
 * live goes straight back to it.
 */
import { createRouter } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";
import { routeTree } from "@/routeTree.gen";

const mocks = vi.hoisted(() => ({
  captcha: null as { provider: string; site_key: string } | null,
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ captcha: mocks.captcha }),
}));

// Stands in for the vendor's widget: a button that hands the page a solve.
vi.mock("@/components/auth/CaptchaWidget", () => ({
  CaptchaWidget: ({ onToken }: { onToken: (token: string) => void }) => (
    <button type="button" onClick={() => onToken("solved")}>
      solve captcha
    </button>
  ),
}));

const ROUTE_ID = "/_serverRequired/demo";
const REDEEM = "/api/v1/demo/redeem";
const COPY = "/api/v1/demo/copy";
const router = createRouter({ routeTree, context: buildRouterContext() });

const openLink = async (
  fragment: string | null,
  options: Omit<Parameters<typeof renderPage>[1], "initialRoute"> = {}
) => {
  window.history.replaceState(null, "", fragment === null ? "/demo" : `/demo#${fragment}`);
  const Page = router.routesById[ROUTE_ID].options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  await Page.preload?.();
  return renderPage(Page, { initialRoute: "/demo", auth: { user: null }, ...options });
};

beforeEach(() => {
  mocks.captcha = null;
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

describe("the demo page", () => {
  it("is served outside the signed-in layout", () => {
    expect(router.matchRoutes("/demo", {}).at(-1)?.routeId).toBe(ROUTE_ID);
  });

  it("takes the token out of the address, signs in with it and lands in the copy", async () => {
    mocks.captcha = { provider: "hcaptcha", site_key: "key" };
    const sent: unknown[] = [];
    server.use(
      http.post(REDEEM, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({ access_token: "demo-token", community_id: 7, import_job_id: 3 });
      })
    );
    const applySignIn = vi.fn();
    const { router: mounted } = await openLink("tok-1", { auth: { user: null, applySignIn } });

    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/demo");

    const user = userEvent.setup();
    const start = await screen.findByRole("button", { name: "Start the demo" });
    expect(start).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "solve captcha" }));
    await user.type(screen.getByLabelText("Email (optional)"), "pat@example.com");
    await user.click(start);

    await waitFor(() => expect(mounted.state.location.pathname).toBe("/c/7"));
    expect(sent).toEqual([{ token: "tok-1", captcha_token: "solved", email: "pat@example.com" }]);
    expect(applySignIn).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: "demo-token", community_id: 7 })
    );
  });

  it("waits for the copy to be filled before going in, and says when that takes too long", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let ready = false;
    server.use(http.get(COPY, () => HttpResponse.json({ community_id: 7, ready })));
    const { router: mounted } = await openLink("tok-1");

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: "Start the demo" }));

    expect(await screen.findByText("Setting up your demo…")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your demo is taking longer than it should to set up."
    );
    expect(mounted.state.location.pathname).toBe("/demo");

    ready = true;
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(mounted.state.location.pathname).toBe("/c/7"));
  });

  it("tells someone signed in to their own account that starting signs them out of it", async () => {
    await openLink("tok-1", { auth: { user: buildUser({ demo_expires_at: null }) } });

    expect(
      await screen.findByText(
        "You're signed in. Starting the demo signs you out of your account and into a demo one."
      )
    ).toBeInTheDocument();
  });

  it("says when every copy is taken, and starts on a retry", async () => {
    let busy = true;
    server.use(
      http.post(REDEEM, () =>
        busy
          ? HttpResponse.json({ detail: "DEMO_BUSY" }, { status: 503 })
          : HttpResponse.json({ access_token: "demo-token", community_id: 7, import_job_id: 3 })
      )
    );
    const { router: mounted } = await openLink("tok-1");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Start the demo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "All demo spaces are busy. Try again in a minute."
    );
    busy = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mounted.state.location.pathname).toBe("/c/7"));
  });

  it("says a link without a working token is dead, and offers no start", async () => {
    await openLink(null);

    expect(
      await screen.findByText(
        "This demo link doesn't work any more. Ask whoever sent it for a new one."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start the demo" })).not.toBeInTheDocument();
  });

  it("sends a visitor whose copy is live back to it without opening another", async () => {
    const redeemed = vi.fn();
    server.use(
      http.post(REDEEM, () => {
        redeemed();
        return HttpResponse.json({});
      })
    );
    const expiresAt = new Date(Date.now() + 60 * 60_000).toISOString();
    server.use(http.get(COPY, () => HttpResponse.json({ community_id: 9, ready: true })));
    const { router: mounted } = await openLink("tok-2", {
      auth: { user: buildUser({ demo_expires_at: expiresAt, demo_community_id: 9 }) },
      communities: { communities: [buildCommunity({ id: 9 })] },
    });

    await waitFor(() => expect(mounted.state.location.pathname).toBe("/c/9"));
    expect(redeemed).not.toHaveBeenCalled();
  });
});

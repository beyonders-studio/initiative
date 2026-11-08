import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { CLOUD_ORIGIN } from "@/lib/cloud";

vi.mock("@/hooks/useTickets", async () => ({
  ...(await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets")),
  useTicketAvailability: () => ({ data: undefined }),
  useFileTicket: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { contextFromFragment, FeedbackPage } from "./FeedbackPage";

describe("FeedbackPage", () => {
  it("reads where it was sent from out of the fragment, and nothing else", () => {
    expect(contextFromFragment("#app_version=0.79.0&route=%2Fc%2F%24communityId&token=x")).toEqual({
      app_version: "0.79.0",
      route: "/c/$communityId",
    });
    expect(contextFromFragment("")).toBeNull();
  });

  it("sends somebody signed out to sign in, and keeps what they wrote for when they are back", async () => {
    const user = userEvent.setup();
    const cloud = { getServerOrigin: () => CLOUD_ORIGIN };
    const first = renderPage(FeedbackPage, {
      initialRoute: "/feedback",
      routerHash: "app_version=0.79.0&route=%2Fc%2F%24communityId",
      server: cloud,
      auth: { user: null },
    });
    await user.type(
      await screen.findByLabelText("What would you like Initiative to do?"),
      "Dark print."
    );
    await user.click(screen.getByRole("button", { name: "Sign in to send" }));
    expect(first.router.state.location.pathname).toBe("/login");
    expect(first.router.state.location.search).toEqual({ next: "/feedback" });
    first.unmount();

    renderPage(FeedbackPage, { initialRoute: "/feedback", server: cloud, auth: { user: null } });
    expect(await screen.findByLabelText("What would you like Initiative to do?")).toHaveValue(
      "Dark print."
    );
    await user.click(screen.getByRole("button", { name: "See what" }));
    expect(screen.getByText("0.79.0")).toBeInTheDocument();
  });
});

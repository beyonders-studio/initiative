import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { SubscribeButton } from "./SubscribeButton";

// `subscribed` is the worked-out answer; `subscribed_at` is only a by-hand subscription.
const state = (subscribed: boolean, subscribed_at: string | null = null) => ({
  entity_type: "task",
  entity_id: 7,
  viewed_at: null,
  view_source: null,
  bookmarked_at: null,
  subscribed_at,
  subscribed,
});

describe("SubscribeButton", () => {
  it("reads whether the item is subscribed to, subscribes to it, and puts it back when that fails", async () => {
    const user = userEvent.setup();
    let subscribed = false;
    let fail = false;
    const written: string[] = [];
    server.use(
      http.get("/api/v1/c/3/personal-items/task/7", () => HttpResponse.json(state(subscribed))),
      http.put("/api/v1/c/3/personal-items/subscribe/:kind/:id", ({ params }) => {
        written.push(`subscribe ${params.kind}/${params.id}`);
        if (fail) return new HttpResponse(null, { status: 404 });
        subscribed = true;
        return HttpResponse.json(state(subscribed, "2026-10-17T00:00:00Z"));
      }),
      http.delete("/api/v1/c/3/personal-items/subscribe/:kind/:id", ({ params }) => {
        written.push(`unsubscribe ${params.kind}/${params.id}`);
        subscribed = false;
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<SubscribeButton kind="task" entityId={7} />, {
      communities: { activeCommunityId: 3 },
    });

    const button = await screen.findByRole("button", { name: "Subscribe" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    const unsubscribe = await screen.findByRole("button", { name: "Unsubscribe" });
    expect(unsubscribe).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(unsubscribe).toBeEnabled());

    await user.click(unsubscribe);
    await screen.findByRole("button", { name: "Subscribe" });
    expect(written).toEqual(["subscribe task/7", "unsubscribe task/7"]);

    fail = true;
    await waitFor(() => expect(screen.getByRole("button", { name: "Subscribe" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Subscribe" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Subscribe" })).toHaveAttribute(
        "aria-pressed",
        "false"
      )
    );
  });

  it("reads what the reader made as subscribed, with no subscription by hand", async () => {
    server.use(http.get("/api/v1/c/3/personal-items/task/7", () => HttpResponse.json(state(true))));
    renderWithProviders(<SubscribeButton kind="task" entityId={7} />, {
      communities: { activeCommunityId: 3 },
    });

    expect(await screen.findByRole("button", { name: "Unsubscribe" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});

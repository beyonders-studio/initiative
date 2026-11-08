/**
 * A subscription link is a personal API key that names one calendar, made
 * through the ordinary key route and shown once as the calendar's feed URL.
 * A page with several calendars offers a link for each, so each stays its own
 * calendar in the other app.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { type ApiKeyMetadata, Tool } from "@/api/generated/initiativeAPI.schemas";

import {
  CalendarSubscribeDialog,
  isSubscription,
  NewSubscriptionLinkDialog,
} from "./CalendarSubscribeDialog";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const CALENDAR = { id: 7, name: "Rehearsals" };

const key = (overrides: Partial<ApiKeyMetadata> = {}): ApiKeyMetadata => ({
  id: 1,
  name: "Calendar: Rehearsals",
  token_prefix: "ppk_abcdefgh",
  is_active: true,
  read_only: true,
  community_id: 1,
  resource_type: Tool.calendar,
  resource_id: CALENDAR.id,
  created_at: "2026-01-01T00:00:00Z",
  last_used_at: null,
  expires_at: null,
  ...overrides,
});

const renderDialog = (calendars = [CALENDAR]) =>
  renderWithProviders(
    <CalendarSubscribeDialog open onOpenChange={() => {}} communityId={1} calendars={calendars} />
  );

describe("CalendarSubscribeDialog", () => {
  it("makes a key naming this calendar and shows its feed URL", async () => {
    let body: unknown;
    server.use(
      http.get("/api/v1/me/api-keys", () => HttpResponse.json({ keys: [] })),
      http.post("/api/v1/me/api-keys", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ api_key: key(), secret: "ppk_secret" }, { status: 201 });
      })
    );
    renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Get link" }));

    expect(body).toMatchObject({
      community_id: 1,
      resource_type: "calendar",
      resource_id: CALENDAR.id,
    });
    expect(
      await screen.findByText(/\/api\/v1\/c\/1\/calendars\/7\/feed\.ics\?token=ppk_secret$/)
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in calendar app" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^webcal:\/\/.*\/feed\.ics\?token=ppk_secret$/)
    );
  });

  it("says a new link replaces the one already made", async () => {
    server.use(http.get("/api/v1/me/api-keys", () => HttpResponse.json({ keys: [key()] })));
    renderDialog();

    expect(await screen.findByRole("button", { name: "Get a new link" })).toBeInTheDocument();
    expect(screen.getByText(/stops the old one working/)).toBeInTheDocument();
  });

  it("makes a separate link for the calendar picked from several", async () => {
    let body: unknown;
    server.use(
      http.get("/api/v1/me/api-keys", () => HttpResponse.json({ keys: [key()] })),
      http.post("/api/v1/me/api-keys", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          { api_key: key({ id: 2, resource_id: 8 }), secret: "ppk_other" },
          { status: 201 }
        );
      })
    );
    renderDialog([CALENDAR, { id: 8, name: "Matches" }]);

    // Rehearsals already has a link; Matches does not.
    expect(await screen.findByRole("button", { name: "Get a new link" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Get link" }));

    expect(body).toMatchObject({ resource_type: "calendar", resource_id: 8 });
    expect(
      await screen.findByText(/\/calendars\/8\/feed\.ics\?token=ppk_other$/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get a new link" })).toBeInTheDocument();
  });
});

describe("NewSubscriptionLinkDialog", () => {
  it("replaces a subscription's key under its own name and shows the new link (#2911)", async () => {
    let body: unknown;
    server.use(
      http.post("/api/v1/me/api-keys", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ api_key: key({ id: 2 }), secret: "ppk_fresh" }, { status: 201 });
      })
    );
    const subscription = key();
    if (!isSubscription(subscription)) throw new Error("a calendar's key is a subscription");
    renderWithProviders(<NewSubscriptionLinkDialog apiKey={subscription} onClose={() => {}} />);

    expect(screen.getByText(/current link stops working/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Get a new link" }));

    expect(body).toMatchObject({
      name: "Calendar: Rehearsals",
      community_id: 1,
      resource_type: "calendar",
      resource_id: CALENDAR.id,
    });
    expect(
      await screen.findByText(/\/api\/v1\/c\/1\/calendars\/7\/feed\.ics\?token=ppk_fresh$/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("stays open while the new link is made, as the old one is already gone", async () => {
    let answer: () => void = () => {};
    server.use(
      http.post(
        "/api/v1/me/api-keys",
        () =>
          new Promise<Response>((resolve) => {
            answer = () =>
              resolve(
                HttpResponse.json({ api_key: key({ id: 2 }), secret: "ppk_late" }, { status: 201 })
              );
          })
      )
    );
    const onClose = vi.fn();
    const subscription = key();
    if (!isSubscription(subscription)) throw new Error("a calendar's key is a subscription");
    renderWithProviders(<NewSubscriptionLinkDialog apiKey={subscription} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: "Get a new link" }));
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toBeDisabled());
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    answer();
    expect(await screen.findByText(/token=ppk_late$/)).toBeInTheDocument();
  });

  it("is offered only for a calendar's key", () => {
    expect(isSubscription(key())).toBe(true);
    expect(isSubscription(key({ resource_type: null, resource_id: null, read_only: false }))).toBe(
      false
    );
  });
});

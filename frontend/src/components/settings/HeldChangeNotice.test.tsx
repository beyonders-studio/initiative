/**
 * The change an account has waiting, on its settings pages.
 *
 * It says what will happen and when, Cancel cancels it, and an account with a
 * passkey makes it now by signing in again with one first.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { HeldChangeNotice } from "./HeldChangeNotice";

vi.mock("@/lib/passkeys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/passkeys")>()),
  passkeysRunHere: () => true,
}));

const HELD = {
  id: 7,
  kind: "primary",
  subject: "new@example.com",
  requested_at: "2026-10-03T08:00:00Z",
  applies_at: "2026-10-05T08:00:00Z",
};

const answering = (passkeys: unknown[]) => {
  const calls: string[] = [];
  server.use(
    http.get("/api/v1/me/held-change", () => HttpResponse.json(HELD)),
    http.get("/api/v1/auth/passkeys", () => HttpResponse.json({ passkeys, limit: 10 })),
    http.post("/api/v1/me/held-change/7/cancel", () => {
      calls.push("cancel");
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("/api/v1/me/held-change/7/apply", () => {
      calls.push("apply");
      return new HttpResponse(null, { status: 204 });
    })
  );
  return calls;
};

describe("HeldChangeNotice", () => {
  it("says what waits and cancels it", async () => {
    const user = userEvent.setup();
    const calls = answering([]);

    renderWithProviders(<HeldChangeNotice />);

    expect(
      await screen.findByText(/new@example.com becomes your primary address/i)
    ).toBeInTheDocument();
    // Nothing to sign in again with, so nothing offers to.
    expect(screen.queryByRole("button", { name: /with a passkey/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel the change/i }));
    await waitFor(() => expect(calls).toEqual(["cancel"]));
  });

  it("makes it now after a passkey step-up", async () => {
    const user = userEvent.setup();
    const calls = answering([{ id: "pk-1", name: "Phone" }]);
    const stepUpWithPasskey = vi.fn(async () => {
      calls.push("step-up");
    });

    renderWithProviders(<HeldChangeNotice />, { auth: { stepUpWithPasskey } });

    await user.click(await screen.findByRole("button", { name: /make it now with a passkey/i }));
    await waitFor(() => expect(calls).toEqual(["step-up", "apply"]));
  });
});

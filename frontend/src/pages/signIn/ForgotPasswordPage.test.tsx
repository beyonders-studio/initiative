/**
 * The way back in for an account with no password to reset.
 *
 * The mailed link is the usual road and is left alone here. What this pins is
 * the other one: the card swaps to a form that carries three things — the
 * address, a recovery code and the password being set — and says what happened
 * when the server is done with them.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { ForgotPasswordPage } from "./ForgotPasswordPage";

const fillRecoverForm = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("button", { name: /use a recovery code/i }));
  await user.type(await screen.findByLabelText(/email/i), "Someone@Example.com");
  await user.type(screen.getByLabelText(/recovery code/i), "aaaaa-bbbbb");
  await user.type(screen.getByLabelText(/new password/i), "a-long-enough-password");
  await user.type(screen.getByLabelText(/confirm password/i), "a-long-enough-password");
  await user.click(screen.getByRole("button", { name: /set password/i }));
};

describe("ForgotPasswordPage", () => {
  it("offers no form where the deployment takes no password", async () => {
    server.use(http.get("/api/v1/config", () => HttpResponse.json({ login_methods: ["sso"] })));

    renderPage(ForgotPasswordPage, { initialRoute: "/forgot-password" });

    expect(await screen.findByText(/password sign-in is off/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("sets a password from a recovery code", async () => {
    const user = userEvent.setup();
    let body: unknown = null;
    server.use(
      http.post("/api/v1/auth/password/recover", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ status: "reset" });
      })
    );

    renderPage(ForgotPasswordPage, { initialRoute: "/forgot-password" });
    await fillRecoverForm(user);

    expect(await screen.findByText(/your password is set/i)).toBeInTheDocument();
    expect(body).toEqual({
      // Lower-cased on the way out, as the reset form does with an address.
      email: "someone@example.com",
      recovery_code: "aaaaa-bbbbb",
      password: "a-long-enough-password",
    });
    expect(screen.getByRole("link", { name: /go to sign in/i })).toBeInTheDocument();
  });

  it("reads the server's line when the code is not one of the account's", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/auth/password/recover", () =>
        HttpResponse.json({ detail: "RECOVERY_CODE_INVALID" }, { status: 400 })
      )
    );

    renderPage(ForgotPasswordPage, { initialRoute: "/forgot-password" });
    await fillRecoverForm(user);

    expect(await screen.findByText(/already been used/i)).toBeInTheDocument();
    expect(screen.queryByText(/your password is set/i)).not.toBeInTheDocument();
  });
});

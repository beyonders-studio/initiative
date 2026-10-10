import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { EmailOtpCard } from "./EmailOtpCard";

/** What the deployment says it runs. Set per test; no captcha is the default. */
const mocks = vi.hoisted(() => ({
  captcha: null as { provider: string; site_key: string } | null,
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ captcha: mocks.captcha }),
}));

// Stands in for the vendor's widget, which loads its script over the network:
// a button that hands the card a solve, which is all the card knows about it.
vi.mock("@/components/auth/CaptchaWidget", () => ({
  CaptchaWidget: ({ onToken }: { onToken: (token: string) => void }) => (
    <button type="button" onClick={() => onToken("solved")}>
      solve captcha
    </button>
  ),
}));

const mount = async (props: Partial<Parameters<typeof EmailOtpCard>[0]> = {}) => {
  const onSignedIn = vi.fn();
  const onCancel = vi.fn();
  const applySignIn = vi.fn();
  const result = renderPage(
    () => <EmailOtpCard onSignedIn={onSignedIn} onCancel={onCancel} {...props} />,
    { auth: { applySignIn } }
  );
  await waitFor(() => {
    expect(result.router.state.status).toBe("idle");
  });
  return { onSignedIn, onCancel, applySignIn };
};

/** Ask for a code at an address and land on the code step. */
const askAt = async (address: string) => {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/email/i), address);
  await user.click(screen.getByRole("button", { name: /email me a code/i }));
  await screen.findByLabelText(/^code$/i);
  return user;
};

describe("EmailOtpCard", () => {
  beforeEach(() => {
    mocks.captcha = null;
  });

  it("signs in when the code belongs to an account", async () => {
    const sent: Record<string, string>[] = [];
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-1" })
      ),
      http.post("/api/v1/auth/email-otp/verify", async ({ request }) => {
        sent.push((await request.json()) as Record<string, string>);
        return HttpResponse.json({ access_token: "a-token", token_type: "bearer" });
      })
    );
    const { onSignedIn, applySignIn } = await mount();

    const user = await askAt("reader@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "123456");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(false));
    expect(applySignIn).toHaveBeenCalledWith(expect.objectContaining({ access_token: "a-token" }));
    expect(sent).toEqual([{ challenge: "handle-1", code: "123456" }]);
  });

  it("asks for a username when the address belongs to nobody yet", async () => {
    const registered: Record<string, unknown>[] = [];
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-2" })
      ),
      http.post("/api/v1/auth/email-otp/verify", () =>
        HttpResponse.json({ registration_ticket: "ticket-2" }, { status: 202 })
      ),
      http.post("/api/v1/auth/email-otp/register", async ({ request }) => {
        registered.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          { access_token: "new-token", token_type: "bearer" },
          { status: 201 }
        );
      })
    );
    // What the start flow already asked goes out with the account.
    const { onSignedIn, applySignIn } = await mount({
      registration: { community: { name: "Riverside Players" } },
    });

    const user = await askAt("newcomer@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "654321");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    const username = await screen.findByLabelText(/username/i);
    await user.type(username, "newcomer");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(true));
    expect(applySignIn).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: "new-token" })
    );
    expect(registered[0]).toMatchObject({
      registration_ticket: "ticket-2",
      username: "newcomer",
      community: { name: "Riverside Players" },
    });
  });

  it("keeps the code step when the code is refused", async () => {
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-3" })
      ),
      http.post("/api/v1/auth/email-otp/verify", () =>
        HttpResponse.json({ detail: "EMAIL_OTP_INVALID" }, { status: 400 })
      )
    );
    const { onSignedIn } = await mount();

    const user = await askAt("wrong@example.com");
    await user.type(screen.getByLabelText(/^code$/i), "000000");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText(/^code$/i)).toBeInTheDocument();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("asks for a code without a captcha where the deployment runs none", async () => {
    const asked: Record<string, unknown>[] = [];
    server.use(
      http.post("/api/v1/auth/email-otp/send", async ({ request }) => {
        asked.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ status: "sent", challenge: "handle-5" });
      })
    );
    await mount();

    await askAt("plain@example.com");

    // A browser asks for itself; only the app says it is native.
    expect(asked).toEqual([{ email: "plain@example.com" }]);
  });

  it("sends the captcha the deployment asks for", async () => {
    mocks.captcha = { provider: "hcaptcha", site_key: "site" };
    const asked: Record<string, unknown>[] = [];
    server.use(
      http.post("/api/v1/auth/email-otp/send", async ({ request }) => {
        asked.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ status: "sent", challenge: "handle-6" });
      })
    );
    await mount();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/email/i), "guarded@example.com");
    // Nothing is asked for until the captcha is answered — that is the one
    // refusal this route makes, and it makes it before the address is read.
    expect(screen.getByRole("button", { name: /email me a code/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /solve captcha/i }));
    await user.click(screen.getByRole("button", { name: /email me a code/i }));
    await screen.findByLabelText(/^code$/i);

    expect(asked).toEqual([{ email: "guarded@example.com", captcha_token: "solved" }]);
  });

  it("asks for a fresh solve after a refused send", async () => {
    mocks.captcha = { provider: "hcaptcha", site_key: "site" };
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ detail: "CAPTCHA_INVALID" }, { status: 400 })
      )
    );
    await mount();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/email/i), "guarded@example.com");
    await user.click(screen.getByRole("button", { name: /solve captcha/i }));
    await user.click(screen.getByRole("button", { name: /email me a code/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    // A token is spent by being checked, so the one just sent buys nothing.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /email me a code/i })).toBeDisabled()
    );
  });

  it("goes back to the address when it was typed wrong", async () => {
    server.use(
      http.post("/api/v1/auth/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-4" })
      )
    );
    await mount();

    const user = await askAt("typo@example.com");
    await user.click(screen.getByRole("button", { name: /wrong address/i }));

    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument();
  });
});

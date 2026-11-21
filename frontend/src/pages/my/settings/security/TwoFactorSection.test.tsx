/**
 * Turning two-factor on, off, and round again.
 *
 * The section's own job is small but easy to get subtly wrong: the password
 * step serves two errands and they must not be confused, "turn off" takes
 * either kind of code and has to send each as the kind it is, and an account
 * with no password is set up and turned off without being asked for one.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { TwoFactorSection } from "./TwoFactorSection";

const notEnrolled = {
  enrolled: false,
  recovery_codes_remaining: 0,
  password_required: true,
  offered: true,
};
/** No password at all, and not enrolled: the codes are still the way back. */
const passwordless = {
  enrolled: false,
  recovery_codes_remaining: 7,
  password_required: false,
  offered: true,
  passwordless: true,
};
const enrolled = {
  enrolled: true,
  confirmed_at: "2026-09-01T10:00:00Z",
  last_used_at: null,
  recovery_codes_remaining: 8,
  password_required: true,
  offered: true,
};

/** Serves the status and answers every write, recording each as `<path> <body>`. */
const serve = (status: object | Response = notEnrolled) => {
  const sent: string[] = [];
  const answer =
    (body: object) =>
    async ({ request }: { request: Request }) => {
      sent.push(
        `${new URL(request.url).pathname.replace("/api/v1/auth/", "")} ${await request.text()}`
      );
      return HttpResponse.json(body);
    };
  server.use(
    http.get("/api/v1/auth/totp", () =>
      status instanceof Response ? status : HttpResponse.json(status)
    ),
    http.post(
      "/api/v1/auth/totp/enroll",
      answer({
        secret: "SEEDSEEDSEED",
        otpauth_uri: "otpauth://totp/example.com:me?secret=SEEDSEEDSEED",
      })
    ),
    http.post("/api/v1/auth/totp/confirm", answer({ codes: ["aaaaa-bbbbb", "ccccc-ddddd"] })),
    // The change was made, with nothing held.
    http.post("/api/v1/auth/totp/disable", answer({ held: null })),
    http.post("/api/v1/auth/recovery-codes/regenerate", answer({ codes: ["eeeee-fffff"] }))
  );
  return sent;
};

describe("TwoFactorSection", () => {
  it("walks password, then scan, then the codes", async () => {
    const user = userEvent.setup();
    const sent = serve();
    renderWithProviders(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: /set up/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // The seed is offered as text as well as a QR, for a device that cannot scan.
    expect(await screen.findByText("SEEDSEEDSEED")).toBeInTheDocument();
    expect(sent).toEqual(['totp/enroll {"current_password":"a-password"}']);

    await user.type(screen.getByLabelText(/code from your app/i), "123456");
    await user.click(screen.getByRole("button", { name: /turn on/i }));

    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
    expect(sent.at(-1)).toBe('totp/confirm {"code":"123456"}');
  });

  it("shows what the account holds once it is on, and asks the regenerate endpoint, not the enrol one", async () => {
    // The password step serves both errands; before it was told which, this
    // button started a fresh enrolment.
    const user = userEvent.setup();
    const sent = serve(enrolled);
    renderWithProviders(<TwoFactorSection />);

    expect(await screen.findByText(/8 recovery codes left/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new recovery codes/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("eeeee-fffff")).toBeInTheDocument();
    expect(sent).toEqual(['recovery-codes/regenerate {"current_password":"a-password"}']);
  });

  it.each([
    ["six digits as a live code", "123456", '"code":"123456"'],
    ["anything else as a recovery code", "aaaaa-bbbbb", '"recovery_code":"aaaaa-bbbbb"'],
    // Authenticator apps render "123 456", and that is what gets copied. Sent
    // as a recovery code it would be checked against the wrong thing.
    [
      "a code copied with the spacing an app shows it in as a live code",
      "123 456",
      '"code":"123456"',
    ],
  ])("sends %s", async (_, typed, field) => {
    const user = userEvent.setup();
    const sent = serve(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), typed);
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(sent).toEqual([`totp/disable {"current_password":"a-password",${field}}`])
    );
  });

  it.each([
    // Unknown is not off: an enrolled account sent to setup only reaches a 409.
    [
      "it could not read the status",
      () => new HttpResponse(null, { status: 500 }),
      /couldn't load this/i,
    ],
    // Withdrawn by the operator. An enrolment already made is left alone, so
    // this says so rather than showing a button the server would refuse.
    [
      "the deployment does not offer it",
      () => ({ ...notEnrolled, offered: false }),
      /does not offer/i,
    ],
  ])("does not offer setup when %s", async (_, status, line) => {
    serve(status());
    renderWithProviders(<TwoFactorSection />);

    expect(await screen.findByText(line)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up/i })).not.toBeInTheDocument();
  });

  it("starts at the code to scan where the account holds no password", async () => {
    // A recent sign-in answers for the missing password.
    const user = userEvent.setup();
    const sent = serve(passwordless);
    renderWithProviders(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: /set up/i }));

    expect(await screen.findByText("SEEDSEEDSEED")).toBeInTheDocument();
    expect(sent).toEqual(['totp/enroll {"current_password":null}']);
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
  });

  it("turns off without a password where the account holds none", async () => {
    const user = userEvent.setup();
    const sent = serve({ ...enrolled, password_required: false });
    renderWithProviders(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: /turn off/i }));
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
    await user.type(await screen.findByLabelText(/recovery code/i), "123456");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(sent).toEqual(['totp/disable {"current_password":null,"code":"123456"}'])
    );
  });

  it("keeps the recovery codes on offer for an account with no password", async () => {
    // Not enrolled, so the block above says nothing about codes — and for this
    // account they are the way to set a password again.
    const user = userEvent.setup();
    const sent = serve(passwordless);
    renderWithProviders(<TwoFactorSection />);

    expect(await screen.findByText(/7 recovery codes left/i)).toBeInTheDocument();
    // Its sign-in may never ask for the code, but a community or the server
    // asking for a second factor will.
    expect(screen.getByRole("button", { name: /set up/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new recovery codes/i }));

    // Nothing to re-check, so no password step stands between the two.
    expect(await screen.findByText("eeeee-fffff")).toBeInTheDocument();
    expect(sent).toEqual(['recovery-codes/regenerate {"current_password":null}']);
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
  });
});

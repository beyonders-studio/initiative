/**
 * The first-owner registration card, which asks the start flow's account step.
 *
 * An account can be made with a key instead of a password, which is what a
 * deployment that has withdrawn passwords needs to take a registration at
 * all. What is worth pinning here is the joins: which buttons a deployment's
 * own settings leave on the card, that a key registration sends the details
 * the form is holding, and that the codes it comes back with are put on
 * screen — they are shown once, and they are the account's only way back to
 * a password.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  applyPasskeySignIn: vi.fn(),
  signUpWithPasskey: vi.fn(),
  passkeysRunHere: vi.fn(() => true),
  /** Read on every render, so a test can say what the deployment offers. */
  config: {
    captcha: null,
    passwordLoginEnabled: true,
    passkeyLoginEnabled: true,
  },
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({
    register: mocks.register,
    login: mocks.login,
    applyPasskeySignIn: mocks.applyPasskeySignIn,
  }),
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => mocks.config,
}));

vi.mock("@/lib/passkeys", () => ({
  passkeysRunHere: () => mocks.passkeysRunHere(),
  signUpWithPasskey: (details: unknown) => mocks.signUpWithPasskey(details),
  describePasskeyPromptError: () => null,
}));

import { RegisterPage } from "./RegisterPage";

const PASSKEY_BUTTON = /create account with a passkey/i;

beforeEach(() => {
  mocks.config = { captcha: null, passwordLoginEnabled: true, passkeyLoginEnabled: true };
  mocks.passkeysRunHere.mockReturnValue(true);
  mocks.signUpWithPasskey.mockReset();
  mocks.applyPasskeySignIn.mockReset();
  mocks.register.mockReset();
});

afterEach(() => vi.clearAllMocks());

const fillIn = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(await screen.findByLabelText(/email/i), "keys@example.com");
  await user.type(screen.getByLabelText("Username"), "keys");
};

it("offers both doors where the deployment leaves both open", async () => {
  renderPage(RegisterPage, { initialRoute: "/login" });
  expect(await screen.findByRole("button", { name: PASSKEY_BUTTON })).toBeInTheDocument();
  expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
});

it("asks for no password where the deployment does not take one", async () => {
  mocks.config = { captcha: null, passwordLoginEnabled: false, passkeyLoginEnabled: true };
  renderPage(RegisterPage, { initialRoute: "/login" });

  expect(await screen.findByRole("button", { name: PASSKEY_BUTTON })).toBeInTheDocument();
  // No password to ask for, so the card does not ask — before this the form
  // required one it could not use.
  expect(screen.queryByLabelText(/^password/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/confirm password/i)).not.toBeInTheDocument();
});

it("keeps the key door shut where the browser cannot open one", async () => {
  mocks.passkeysRunHere.mockReturnValue(false);
  renderPage(RegisterPage, { initialRoute: "/login" });

  await screen.findByLabelText(/^password/i);
  expect(screen.queryByRole("button", { name: PASSKEY_BUTTON })).not.toBeInTheDocument();
});

it("shows the recovery codes a key registration comes back with", async () => {
  const user = userEvent.setup();
  mocks.signUpWithPasskey.mockResolvedValue({
    access_token: "a-session",
    codes: ["aaaa-1111", "bbbb-2222"],
  });
  renderPage(RegisterPage, { initialRoute: "/login" });
  await fillIn(user);
  await user.click(screen.getByRole("button", { name: PASSKEY_BUTTON }));

  await waitFor(() =>
    expect(mocks.signUpWithPasskey).toHaveBeenCalledWith(
      expect.objectContaining({ email: "keys@example.com", username: "keys" })
    )
  );
  // Signed in by the ceremony that made it, and the codes on screen: they are
  // shown once, and they are the account's only way back to a password.
  expect(mocks.applyPasskeySignIn).toHaveBeenCalledWith({ access_token: "a-session" });
  expect(await screen.findByText("aaaa-1111")).toBeInTheDocument();
  expect(screen.getByText("bbbb-2222")).toBeInTheDocument();
});

it("says what a password registration waits on, in place of the form", async () => {
  const user = userEvent.setup();
  mocks.register.mockResolvedValue(buildUser({ status: "active", email_verified: false }));
  renderPage(RegisterPage, { initialRoute: "/login" });
  await fillIn(user);
  await user.type(screen.getByLabelText(/^password/i), "a-long-enough-password");
  await user.type(screen.getByLabelText(/confirm password/i), "a-long-enough-password");
  await user.click(screen.getByRole("button", { name: "Sign up" }));

  expect(await screen.findByText(/check your inbox/i)).toBeInTheDocument();
  expect(mocks.register).toHaveBeenCalledWith(
    expect.objectContaining({
      email: "keys@example.com",
      username: "keys",
      password: "a-long-enough-password",
    })
  );
  // Not signed in until the address is verified; the message replaces the form.
  expect(mocks.login).not.toHaveBeenCalled();
  expect(screen.queryByLabelText(/^password/i)).not.toBeInTheDocument();
});

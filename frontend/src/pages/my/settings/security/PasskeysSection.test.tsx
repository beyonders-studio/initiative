/**
 * Adding, renaming and removing a passkey.
 *
 * The add flow is the part worth pinning down: it is three steps that have to
 * stay joined — the server's options reach the browser, the browser's answer
 * reaches the server, and the name typed at the start travels with it. A
 * prompt that produced nothing has to leave the form as it was, so a second
 * attempt is one click rather than a retype.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { toast } from "@/lib/mascotToast";

const mocks = vi.hoisted(() => ({
  startRegistration: vi.fn(),
  browserSupportsWebAuthn: vi.fn(() => true),
}));

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: (options: unknown) => mocks.startRegistration(options),
  browserSupportsWebAuthn: () => mocks.browserSupportsWebAuthn(),
  WebAuthnError: class WebAuthnError extends Error {},
}));

import { PasskeysSection } from "./PasskeysSection";

const passkey = (overrides: Record<string, unknown> = {}) => ({
  id: "pk-1",
  name: "Work laptop",
  created_at: "2026-09-01T10:00:00Z",
  last_used_at: null,
  backed_up: false,
  user_verified: true,
  transports: ["internal"],
  aaguid: null,
  ...overrides,
});

/**
 * Serves the list and answers every write, recording each as `<path> <body>`.
 * A removal answers `removal` — nothing held, or a refusal.
 */
const serve = (
  passkeys = [passkey()],
  rest: Record<string, unknown> = {},
  removal: Response = HttpResponse.json({ held: null })
) => {
  const sent: string[] = [];
  const record = async (request: Request) =>
    sent.push(`${new URL(request.url).pathname} ${await request.text()}`);
  server.use(
    http.get("/api/v1/auth/passkeys", () =>
      HttpResponse.json({
        passkeys,
        password_required: true,
        limit: 10,
        site_supported: true,
        offered: true,
        ...rest,
      })
    ),
    http.post("/api/v1/auth/passkeys/register/begin", async ({ request }) => {
      await record(request);
      return HttpResponse.json({ options: { challenge: "a-challenge" } });
    }),
    http.post("/api/v1/auth/passkeys/register/finish", async ({ request }) => {
      await record(request);
      return HttpResponse.json(passkey({ id: "pk-new" }));
    }),
    http.patch("/api/v1/auth/passkeys/:id", async ({ request }) => {
      await record(request);
      return HttpResponse.json(passkey());
    }),
    http.post("/api/v1/auth/passkeys/:id/remove", async ({ request }) => {
      await record(request);
      return removal;
    })
  );
  return sent;
};

const BEGIN =
  '/api/v1/auth/passkeys/register/begin {"current_password":"a-password","name":"Phone"}';

/** Open the add dialog, name the passkey, give the password, and go on. */
const add = async (user: ReturnType<typeof userEvent.setup>, name = "Phone") => {
  await user.click(await screen.findByRole("button", { name: /add a passkey/i }));
  await user.type(await screen.findByLabelText(/^name$/i), name);
  await user.type(screen.getByLabelText(/current password/i), "a-password");
  await user.click(screen.getByRole("button", { name: /continue/i }));
};

/** Ask to remove the one passkey, and confirm with the password. */
const removeIt = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("button", { name: /remove/i }));
  await user.type(await screen.findByLabelText(/current password/i), "a-password");
  await user.click(screen.getAllByRole("button", { name: /remove/i }).at(-1) as HTMLElement);
};

describe("PasskeysSection", () => {
  beforeEach(() => {
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    vi.clearAllMocks();
    mocks.browserSupportsWebAuthn.mockReturnValue(true);
    mocks.startRegistration.mockResolvedValue({ id: "credential-id", type: "public-key" });
  });

  it("names what the account holds, and marks the ones that travel", async () => {
    serve([passkey(), passkey({ id: "pk-2", name: "Phone", backed_up: true })]);
    renderWithProviders(<PasskeysSection />);

    expect(await screen.findByText("Work laptop")).toBeInTheDocument();
    expect(screen.getByText("Phone")).toBeInTheDocument();
    expect(screen.getByText(/synced/i)).toBeInTheDocument();
  });

  it("says what a passkey is when there are none", async () => {
    serve([]);
    renderWithProviders(<PasskeysSection />);

    expect(await screen.findByText(/no passkeys yet/i)).toBeInTheDocument();
    expect(screen.getByText(/password manager/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeEnabled();
  });

  it("carries the server's options to the browser and the browser's answer back", async () => {
    const user = userEvent.setup();
    const sent = serve();
    renderWithProviders(<PasskeysSection />);

    await add(user);

    await waitFor(() =>
      expect(sent).toEqual([
        BEGIN,
        '/api/v1/auth/passkeys/register/finish {"credential":{"id":"credential-id","type":"public-key"},"name":"Phone"}',
      ])
    );
    expect(mocks.startRegistration).toHaveBeenCalledWith({
      optionsJSON: { challenge: "a-challenge" },
    });
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it("keeps the form and the typed name when the prompt produces nothing", async () => {
    const user = userEvent.setup();
    const cancelled = new Error("The operation either timed out or was not allowed.");
    cancelled.name = "NotAllowedError";
    mocks.startRegistration.mockRejectedValue(cancelled);
    const sent = serve();
    renderWithProviders(<PasskeysSection />);

    await add(user);

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(sent).toEqual([BEGIN]);
    expect(screen.getByLabelText(/^name$/i)).toHaveValue("Phone");
  });

  it.each([
    ["this device already holds one for the site", "InvalidStateError", /already holds a passkey/i],
    [
      "the address is not the one the site is set up under",
      "SecurityError",
      /doesn't match the address/i,
    ],
  ])("says so when %s", async (_, errorName, line) => {
    const user = userEvent.setup();
    const refused = new Error("The browser refused.");
    refused.name = errorName;
    mocks.startRegistration.mockRejectedValue(refused);
    serve();
    renderWithProviders(<PasskeysSection />);

    await add(user);

    expect(await screen.findByText(line)).toBeInTheDocument();
  });

  it("asks for the password before taking a way in away", async () => {
    const user = userEvent.setup();
    const sent = serve();
    renderWithProviders(<PasskeysSection />);

    await removeIt(user);

    await waitFor(() =>
      expect(sent).toEqual(['/api/v1/auth/passkeys/pk-1/remove {"current_password":"a-password"}'])
    );
  });

  it("says so when the passkey is the account's only way in", async () => {
    // The server refuses, and the line it names is the one to read — the
    // generic "couldn't do that" would leave nothing to act on.
    const user = userEvent.setup();
    serve(
      [passkey()],
      {},
      HttpResponse.json({ detail: "PASSKEY_IS_LAST_METHOD" }, { status: 409 })
    );
    renderWithProviders(<PasskeysSection />);

    await removeIt(user);

    expect(await screen.findByText(/only way into this account/i)).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("sends a new name on its own", async () => {
    const user = userEvent.setup();
    const sent = serve();
    renderWithProviders(<PasskeysSection />);

    await user.click(await screen.findByRole("button", { name: /rename/i }));
    const field = await screen.findByLabelText(/^name$/i);
    await user.clear(field);
    await user.type(field, "Old laptop");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toEqual(['/api/v1/auth/passkeys/pk-1 {"name":"Old laptop"}']));
  });

  it.each([
    [
      "at the limit",
      () => serve([passkey(), passkey({ id: "pk-2", name: "Phone" })], { limit: 2 }),
      /remove one to add another/i,
      [],
    ],
    [
      "where the browser cannot make it",
      () => {
        mocks.browserSupportsWebAuthn.mockReturnValue(false);
        serve();
      },
      /can't make a passkey/i,
      [],
    ],
    [
      // A deployment served over plain http offers no credential API at all,
      // so the browser looks incapable when the address is what is wrong:
      // the deployment is blamed, not the browser.
      "where the page cannot hold a credential",
      () => {
        Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
        mocks.browserSupportsWebAuthn.mockReturnValue(false);
        serve();
      },
      /proper domain name/i,
      [/can't make a passkey/i],
    ],
    [
      "where the server says its address cannot carry one",
      () => serve([passkey()], { site_supported: false }),
      /proper domain name/i,
      [/can't make a passkey/i],
    ],
  ])("stops offering to add one %s", async (_, arrange, reason, notSaid) => {
    arrange();
    renderWithProviders(<PasskeysSection />);

    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    for (const line of notSaid) expect(screen.queryByText(line)).not.toBeInTheDocument();
  });

  it("says a name is spoken for before asking the browser for anything", async () => {
    // The server holds names to the same rule, so a name it will refuse is
    // worth saying here rather than after a credential exists.
    const user = userEvent.setup();
    const sent = serve();
    renderWithProviders(<PasskeysSection />);

    await add(user, "#1 laptop");

    expect(await screen.findByText(/contain # or @/i)).toBeInTheDocument();
    expect(sent).toEqual([]);
    expect(mocks.startRegistration).not.toHaveBeenCalled();
  });

  it("stops offering to add one where the deployment has withdrawn them", async () => {
    // Withdrawn, not gone: what the account holds is still listed, and still
    // has its rename and remove buttons.
    serve([passkey()], { offered: false });
    renderWithProviders(<PasskeysSection />);

    expect(await screen.findByText(/doesn't offer passkeys/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add a passkey/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rename/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
  });
});

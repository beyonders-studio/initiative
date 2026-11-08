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
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { toast } from "@/lib/mascotToast";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  begin: vi.fn(),
  finish: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  /** What the server answers a removal with — nothing, or a refusal. */
  removeRefusal: vi.fn(),
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

vi.mock("@/api/generated/auth/auth", () => ({
  getListPasskeysQueryKey: () => ["/api/v1/auth/passkeys"],
  useListPasskeys: () => mocks.list(),
  useBeginPasskeyRegistration: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void | Promise<void> };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.begin(vars);
      void options?.mutation?.onSuccess?.({ options: { challenge: "a-challenge" } });
    },
    isPending: false,
  }),
  useFinishPasskeyRegistration: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.finish(vars);
      options?.mutation?.onSuccess?.({ id: "pk-new" });
    },
    isPending: false,
  }),
  useRenamePasskey: (options?: { mutation?: { onSuccess?: (data: unknown) => void } }) => ({
    mutate: (vars: unknown) => {
      mocks.rename(vars);
      options?.mutation?.onSuccess?.({ id: "pk-1" });
    },
    isPending: false,
  }),
  useRemovePasskey: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void; onError?: (err: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.remove(vars);
      const refusal = mocks.removeRefusal();
      if (refusal) {
        options?.mutation?.onError?.(refusal);
        return;
      }
      // What the endpoint answers: the change was made, with nothing held.
      options?.mutation?.onSuccess?.({ held: null });
    },
    isPending: false,
  }),
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

const held = (passkeys: ReturnType<typeof passkey>[], rest: Record<string, unknown> = {}) => ({
  data: {
    passkeys,
    password_required: true,
    limit: 10,
    site_supported: true,
    offered: true,
    ...rest,
  },
  isLoading: false,
  isError: false,
});

describe("PasskeysSection", () => {
  beforeEach(() => {
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.browserSupportsWebAuthn.mockReturnValue(true);
    mocks.startRegistration.mockResolvedValue({ id: "credential-id", type: "public-key" });
    mocks.list.mockReturnValue(held([passkey()]));
  });

  it("names what the account holds, and marks the ones that travel", () => {
    mocks.list.mockReturnValue(
      held([passkey(), passkey({ id: "pk-2", name: "Phone", backed_up: true })])
    );
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByText("Work laptop")).toBeInTheDocument();
    expect(screen.getByText("Phone")).toBeInTheDocument();
    expect(screen.getByText(/synced/i)).toBeInTheDocument();
  });

  it("says what a passkey is when there are none", () => {
    mocks.list.mockReturnValue(held([]));
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByText(/no passkeys yet/i)).toBeInTheDocument();
    expect(screen.getByText(/password manager/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeEnabled();
  });

  it("carries the server's options to the browser and the browser's answer back", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.begin).toHaveBeenCalledWith({
      data: { current_password: "a-password", name: "Phone" },
    });
    await waitFor(() =>
      expect(mocks.startRegistration).toHaveBeenCalledWith({
        optionsJSON: { challenge: "a-challenge" },
      })
    );
    await waitFor(() =>
      expect(mocks.finish).toHaveBeenCalledWith({
        data: { credential: { id: "credential-id", type: "public-key" }, name: "Phone" },
      })
    );
    expect(toast.success).toHaveBeenCalled();
  });

  it("keeps the form and the typed name when the prompt produces nothing", async () => {
    const user = userEvent.setup();
    const cancelled = new Error("The operation either timed out or was not allowed.");
    cancelled.name = "NotAllowedError";
    mocks.startRegistration.mockRejectedValue(cancelled);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(mocks.finish).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^name$/i)).toHaveValue("Phone");
  });

  it("says so when this device already holds one for the site", async () => {
    const user = userEvent.setup();
    const already = new Error("The authenticator was previously registered.");
    already.name = "InvalidStateError";
    mocks.startRegistration.mockRejectedValue(already);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/already holds a passkey/i)).toBeInTheDocument();
  });

  it("says so when the address is not the one the site is set up under", async () => {
    const user = userEvent.setup();
    const mismatch = new Error("The relying party ID is not a registrable domain suffix.");
    mismatch.name = "SecurityError";
    mocks.startRegistration.mockRejectedValue(mismatch);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/doesn't match the address/i)).toBeInTheDocument();
  });

  it("asks for the password before taking a way in away", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /remove/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getAllByRole("button", { name: /remove/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.remove).toHaveBeenCalledWith({
        passkeyId: "pk-1",
        data: { current_password: "a-password" },
      })
    );
  });

  it("says so when the passkey is the account's only way in", async () => {
    // The server refuses, and the line it names is the one to read — the
    // generic "couldn't do that" would leave nothing to act on.
    const user = userEvent.setup();
    mocks.removeRefusal.mockReturnValue({
      response: { status: 409, data: { detail: "PASSKEY_IS_LAST_METHOD" } },
    });
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /remove/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getAllByRole("button", { name: /remove/i }).at(-1) as HTMLElement);

    expect(await screen.findByText(/only way into this account/i)).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("sends a new name on its own", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /rename/i }));
    const field = await screen.findByLabelText(/^name$/i);
    await user.clear(field);
    await user.type(field, "Old laptop");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(mocks.rename).toHaveBeenCalledWith({
        passkeyId: "pk-1",
        data: { name: "Old laptop" },
      })
    );
  });

  it("stops offering to add one at the limit", () => {
    mocks.list.mockReturnValue(
      held([passkey(), passkey({ id: "pk-2", name: "Phone" })], { limit: 2 })
    );
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/remove one to add another/i)).toBeInTheDocument();
  });

  it("stops offering to add one where the browser cannot make it", () => {
    mocks.browserSupportsWebAuthn.mockReturnValue(false);
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/can't make a passkey/i)).toBeInTheDocument();
  });

  it("blames the deployment, not the browser, where the page cannot hold a credential", () => {
    // A deployment served over plain http offers no credential API at all, so
    // the browser looks incapable when the address is what is wrong.
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    mocks.browserSupportsWebAuthn.mockReturnValue(false);
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/proper domain name/i)).toBeInTheDocument();
    expect(screen.queryByText(/can't make a passkey/i)).not.toBeInTheDocument();
  });

  it("takes the server's word for what the address it is configured under can carry", () => {
    mocks.list.mockReturnValue(held([passkey()], { site_supported: false }));
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/proper domain name/i)).toBeInTheDocument();
    expect(screen.queryByText(/can't make a passkey/i)).not.toBeInTheDocument();
  });

  it("says a name is spoken for before asking the browser for anything", async () => {
    // The server holds names to the same rule, so a name it will refuse is
    // worth saying here rather than after a credential exists.
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "#1 laptop");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/contain # or @/i)).toBeInTheDocument();
    expect(mocks.begin).not.toHaveBeenCalled();
    expect(mocks.startRegistration).not.toHaveBeenCalled();
  });

  it("stops offering to add one where the deployment has withdrawn them", () => {
    // Withdrawn, not gone: what the account holds is still listed, and still
    // has its rename and remove buttons.
    mocks.list.mockReturnValue(held([passkey()], { offered: false }));
    renderWithProviders(<PasskeysSection />);

    expect(screen.queryByRole("button", { name: /add a passkey/i })).not.toBeInTheDocument();
    expect(screen.getByText(/doesn't offer passkeys/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rename/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
  });
});

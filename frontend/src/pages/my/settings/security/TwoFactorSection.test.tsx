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
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  begin: vi.fn(),
  confirm: vi.fn(),
  disable: vi.fn(),
  regenerate: vi.fn(),
}));

vi.mock("@/api/generated/auth/auth", () => ({
  useReadSecondFactor: () => mocks.status(),
  getReadSecondFactorQueryKey: () => ["/api/v1/auth/totp"],
  useBeginSecondFactor: (options?: { mutation?: { onSuccess?: (data: unknown) => void } }) => ({
    mutate: (vars: unknown) => {
      mocks.begin(vars);
      options?.mutation?.onSuccess?.({
        secret: "SEEDSEEDSEED",
        otpauth_uri: "otpauth://totp/example.com:me?secret=SEEDSEEDSEED",
      });
    },
    isPending: false,
  }),
  useConfirmSecondFactor: (options?: { mutation?: { onSuccess?: (data: unknown) => void } }) => ({
    mutate: (vars: unknown) => {
      mocks.confirm(vars);
      options?.mutation?.onSuccess?.({ codes: ["aaaaa-bbbbb", "ccccc-ddddd"] });
    },
    isPending: false,
  }),
  useDisableSecondFactor: (options?: { mutation?: { onSuccess?: (data: unknown) => void } }) => ({
    mutate: (vars: unknown) => {
      mocks.disable(vars);
      // What the endpoint answers: the change was made, with nothing held.
      options?.mutation?.onSuccess?.({ held: null });
    },
    isPending: false,
  }),
  useRegenerateRecoveryCodes: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.regenerate(vars);
      options?.mutation?.onSuccess?.({ codes: ["eeeee-fffff"] });
    },
    isPending: false,
  }),
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ user: { has_federated_identity: false } }),
}));

import { TwoFactorSection } from "./TwoFactorSection";

const notEnrolled = {
  data: { enrolled: false, recovery_codes_remaining: 0, password_required: true, offered: true },
  isLoading: false,
  isError: false,
};
/** No password at all, and not enrolled: the codes are still the way back. */
const passwordless = {
  data: {
    enrolled: false,
    recovery_codes_remaining: 7,
    password_required: false,
    offered: true,
    passwordless: true,
  },
  isLoading: false,
  isError: false,
};
const enrolled = {
  data: {
    enrolled: true,
    confirmed_at: "2026-09-01T10:00:00Z",
    last_used_at: null,
    recovery_codes_remaining: 8,
    password_required: true,
    offered: true,
  },
  isLoading: false,
  isError: false,
};

describe("TwoFactorSection", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.status.mockReturnValue(notEnrolled);
  });

  it("offers to set it up when the account has none", () => {
    renderWithProviders(<TwoFactorSection />);
    expect(screen.getByRole("button", { name: /set up/i })).toBeInTheDocument();
  });

  it("walks password, then scan, then the codes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /set up/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.begin).toHaveBeenCalledWith({ data: { current_password: "a-password" } });
    // The seed is offered as text as well as a QR, for a device that cannot scan.
    expect(await screen.findByText("SEEDSEEDSEED")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/code from your app/i), "123456");
    await user.click(screen.getByRole("button", { name: /turn on/i }));

    expect(mocks.confirm).toHaveBeenCalledWith({ data: { code: "123456" } });
    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
  });

  it("shows what the account holds once it is on", () => {
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    expect(screen.getByText(/8 recovery codes left/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();
  });

  it("asks the regenerate endpoint, not the enrol one", async () => {
    // The password step serves both errands; before it was told which, this
    // button started a fresh enrolment.
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /new recovery codes/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.regenerate).toHaveBeenCalledWith({ data: { current_password: "a-password" } });
    expect(mocks.begin).not.toHaveBeenCalled();
    expect(await screen.findByText("eeeee-fffff")).toBeInTheDocument();
  });

  it("sends six digits as a live code", async () => {
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), "123456");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: "a-password", code: "123456" },
      })
    );
  });

  it("sends anything else as a recovery code", async () => {
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), "aaaaa-bbbbb");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: "a-password", recovery_code: "aaaaa-bbbbb" },
      })
    );
  });

  it("reads a code copied with the spacing an app shows it in", async () => {
    // Authenticator apps render "123 456", and that is what gets copied. Sent
    // as a recovery code it would be checked against the wrong thing.
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), "123 456");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: "a-password", code: "123456" },
      })
    );
  });

  it("does not offer setup when it could not read the status", () => {
    // Unknown is not off: an enrolled account sent to setup only reaches a 409.
    mocks.status.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    renderWithProviders(<TwoFactorSection />);

    expect(screen.queryByRole("button", { name: /set up/i })).not.toBeInTheDocument();
    expect(screen.getByText(/couldn't load this/i)).toBeInTheDocument();
  });

  it("starts at the code to scan where the account holds no password", async () => {
    // A recent sign-in answers for the missing password.
    const user = userEvent.setup();
    mocks.status.mockReturnValue(passwordless);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /set up/i }));

    expect(mocks.begin).toHaveBeenCalledWith({ data: { current_password: null } });
    expect(await screen.findByText("SEEDSEEDSEED")).toBeInTheDocument();
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
  });

  it("turns off without a password where the account holds none", async () => {
    const user = userEvent.setup();
    mocks.status.mockReturnValue({
      ...enrolled,
      data: { ...enrolled.data, password_required: false },
    });
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
    await user.type(await screen.findByLabelText(/recovery code/i), "123456");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: null, code: "123456" },
      })
    );
  });

  it("keeps the recovery codes on offer for an account with no password", async () => {
    // Not enrolled, so the block above says nothing about codes — and for this
    // account they are the way to set a password again.
    const user = userEvent.setup();
    mocks.status.mockReturnValue(passwordless);
    renderWithProviders(<TwoFactorSection />);

    expect(screen.getByText(/7 recovery codes left/i)).toBeInTheDocument();
    // Its sign-in may never ask for the code, but a community or the server
    // asking for a second factor will.
    expect(screen.getByRole("button", { name: /set up/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new recovery codes/i }));

    // Nothing to re-check, so no password step stands between the two.
    expect(mocks.regenerate).toHaveBeenCalledWith({ data: { current_password: null } });
    expect(await screen.findByText("eeeee-fffff")).toBeInTheDocument();
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
  });

  it("does not offer setup where the deployment does not offer it", () => {
    // Withdrawn by the operator. An enrolment already made is left alone, so
    // this says so rather than showing a button the server would refuse.
    mocks.status.mockReturnValue({
      ...notEnrolled,
      data: { ...notEnrolled.data, offered: false },
    });
    renderWithProviders(<TwoFactorSection />);

    expect(screen.queryByRole("button", { name: /set up/i })).not.toBeInTheDocument();
    expect(screen.getByText(/does not offer/i)).toBeInTheDocument();
  });
});

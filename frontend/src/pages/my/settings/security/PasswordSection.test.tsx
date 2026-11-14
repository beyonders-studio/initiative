/**
 * The password section of the security page.
 *
 * Two things it has to get right. Which question it asks: an account that
 * holds a password is changing one and is asked for the old; an account that
 * holds none is setting a first and has nothing to be asked for. And what it
 * offers: giving the password up is on the table only in a browser, only
 * where a passkey is standing ready to take over, and the set of recovery
 * codes that comes back is readable once, here.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

const mocks = vi.hoisted(() => ({
  passkeys: vi.fn(),
  removePassword: vi.fn(),
  removeAnswer: vi.fn(),
  update: vi.fn(),
  refreshUser: vi.fn(),
}));

vi.mock("@/hooks/useUsers", () => ({
  useUpdateCurrentUser: (options: unknown) => {
    mocks.update(options);
    return { mutate: vi.fn(), isPending: false };
  },
}));

vi.mock("@/api/generated/auth/auth", () => ({
  getListPasskeysQueryKey: () => ["/api/v1/auth/passkeys"],
  getReadSecondFactorQueryKey: () => ["/api/v1/auth/totp"],
  useListPasskeys: (options?: unknown) => mocks.passkeys(options),
  useRemovePassword: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void | Promise<void> };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.removePassword(vars);
      void options?.mutation?.onSuccess?.(mocks.removeAnswer());
    },
    isPending: false,
  }),
}));

import { PasswordSection } from "./PasswordSection";

const holding = (count: number, rest: Record<string, unknown> = {}) => ({
  data: {
    passkeys: Array.from({ length: count }, (_, index) => ({ id: `pk-${index}` })),
    password_required: true,
    limit: 10,
    offered: true,
    ...rest,
  },
  isLoading: false,
  isError: false,
});

const render = async (
  user: UserRead = buildUser(),
  options: Parameters<typeof renderPage>[1] = {}
) => {
  const result = renderPage(
    () => <PasswordSection user={user} refreshUser={mocks.refreshUser} />,
    options
  );
  await screen.findByLabelText(/new password/i);
  return result;
};

/** Open the dialog, answer it, and send it. */
const giveUpPassword = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: /remove your password/i }));
  await user.type(
    await screen.findByLabelText(/current password/i, { selector: "#remove-current-password" }),
    "a-password"
  );
  await user.click(
    screen.getAllByRole("button", { name: /remove your password/i }).at(-1) as HTMLElement
  );
};

describe("PasswordSection", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.passkeys.mockReturnValue(holding(1));
    mocks.removeAnswer.mockReturnValue({ codes: [] });
    mocks.refreshUser.mockResolvedValue(undefined);
  });

  it("offers to give the password up only where a passkey can take over", async () => {
    mocks.passkeys.mockReturnValue(holding(0));
    const { unmount } = await render();

    expect(screen.queryByRole("button", { name: /remove your password/i })).not.toBeInTheDocument();
    unmount();

    mocks.passkeys.mockReturnValue(holding(1));
    await render();

    expect(screen.getByRole("button", { name: /remove your password/i })).toBeInTheDocument();
    expect(mocks.passkeys).toHaveBeenCalledWith({ query: { enabled: true } });
  });

  it("does not offer it where the deployment has withdrawn passkeys", async () => {
    mocks.passkeys.mockReturnValue(holding(1, { offered: false }));
    await render();

    expect(screen.queryByRole("button", { name: /remove your password/i })).not.toBeInTheDocument();
  });

  it("sends the password and shows the codes that come back", async () => {
    const user = userEvent.setup();
    mocks.removeAnswer.mockReturnValue({ codes: ["aaaaa-bbbbb", "ccccc-ddddd"] });
    await render();

    await giveUpPassword(user);

    await waitFor(() =>
      expect(mocks.removePassword).toHaveBeenCalledWith({
        data: { current_password: "a-password" },
      })
    );
    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
    expect(screen.getByText("ccccc-ddddd")).toBeInTheDocument();
    expect(mocks.refreshUser).toHaveBeenCalled();
  });

  it("keeps the codes on screen when the account refresh does not land", async () => {
    const user = userEvent.setup();
    mocks.removeAnswer.mockReturnValue({ codes: ["aaaaa-bbbbb", "ccccc-ddddd"] });
    mocks.refreshUser.mockRejectedValue(new Error("offline"));
    await render();

    await giveUpPassword(user);

    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
    await waitFor(() => expect(mocks.refreshUser).toHaveBeenCalled());
    // Shown once: the dialog stays on them whatever the refresh did.
    expect(screen.getByText("aaaaa-bbbbb")).toBeInTheDocument();
    expect(screen.getByText("ccccc-ddddd")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /done/i })).toBeInTheDocument();
  });

  it("sends the app to a browser rather than offering it", async () => {
    await render(buildUser(), { server: { isNativePlatform: true } });

    expect(screen.queryByRole("button", { name: /remove your password/i })).not.toBeInTheDocument();
    expect(screen.getByText(/from a browser signed in to this site/i)).toBeInTheDocument();
    expect(mocks.passkeys).toHaveBeenCalledWith({ query: { enabled: false } });
  });

  it("asks for no current password where the account holds none", async () => {
    await render(buildUser({ has_password: false }));

    // The section's title and its button.
    expect(screen.getAllByText("Set a password")).toHaveLength(2);
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove your password/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/new password/i)).toBeInTheDocument();
    // Nothing on the page reads the list, so nothing asks for it.
    expect(mocks.passkeys).toHaveBeenCalledWith({ query: { enabled: false } });
  });

  it("is left out where this deployment signs nobody in with a password", async () => {
    let configServed = false;
    server.use(
      http.get("/api/v1/config", () => {
        configServed = true;
        return HttpResponse.json({ login_methods: ["passkey"] });
      })
    );
    renderPage(() => <PasswordSection user={buildUser()} refreshUser={mocks.refreshUser} />);

    await waitFor(() => expect(configServed).toBe(true));
    await waitFor(() => expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument());
  });
});

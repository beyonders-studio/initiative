import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { AUTH_FACTOR_REQUIRED_EVENT } from "@/api/client";
import { queryClient } from "@/lib/queryClient";

import { SecondFactorStepUpDialog } from "./SecondFactorStepUpDialog";

const statusIs = (enrolled: boolean) =>
  server.use(
    http.get("/api/v1/auth/totp", () =>
      HttpResponse.json({ enrolled, recovery_codes_remaining: enrolled ? 8 : 0 })
    )
  );

const passkeysAre = (passkeys: { id: string; name: string }[]) =>
  server.use(
    http.get("/api/v1/auth/passkeys", () =>
      HttpResponse.json({ passkeys, limit: 10, password_required: true, offered: true })
    )
  );

/**
 * Mounted the way the app mounts it: inside the router, on the page the
 * refused request was made from. The listener is attached on mount, so the
 * challenge waits for the router to settle.
 */
const mount = async (options: Parameters<typeof renderPage>[1] = {}) => {
  const result = renderPage(SecondFactorStepUpDialog, options);
  await waitFor(() => {
    expect(result.router.state.status).toBe("idle");
  });
  return result;
};

const fireChallenge = ({
  communityId = 4,
  kind = "totp",
  platform,
}: {
  communityId?: number | null;
  kind?: "totp" | "passkey" | "proof";
  platform?: boolean;
} = {}) => {
  act(() => {
    window.dispatchEvent(
      new CustomEvent(AUTH_FACTOR_REQUIRED_EVENT, { detail: { communityId, kind, platform } })
    );
  });
};

describe("SecondFactorStepUpDialog", () => {
  it("stays shut until a community asks", async () => {
    statusIs(true);
    await mount();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("adds the authenticator code to the session already open", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    await userEvent.type(screen.getByLabelText(/authentication code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithFactor).toHaveBeenCalledWith({ code: "123456" });
    });
    // The page behind it carries on rather than needing a reload.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("asks the page again without clearing what its visit found unread", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithFactor } });
    // The app's own client, which the dialog invalidates.
    const visit = ["notifications", "opened", 4, "task", 7];
    const page = ["/api/v1/c/4/tasks/7"];
    queryClient.setQueryData(visit, { comment_ids: [3], since: null });
    queryClient.setQueryData(page, {});

    fireChallenge();
    await screen.findByRole("dialog");
    await userEvent.type(screen.getByLabelText(/authentication code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(queryClient.getQueryState(page)?.isInvalidated).toBe(true);
    });
    expect(queryClient.getQueryState(visit)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  // An authenticator app displays "123 456", and that is what gets pasted.
  // Reading it as the six digits it is proved in
  // `src/lib/secondFactorAnswer.test.ts`.

  it("takes a recovery code instead", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /use a recovery code/i }));

    await userEvent.type(screen.getByLabelText(/recovery code/i), "abcde-fghij");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithFactor).toHaveBeenCalledWith({ recoveryCode: "abcde-fghij" });
    });
  });

  it("keeps the dialog open and says so when the code is refused", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockRejectedValue(new Error("nope"));
    await mount({ auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    await userEvent.type(screen.getByLabelText(/authentication code/i), "000000");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument();
  });

  it("sends an account with no factor to set one up", async () => {
    statusIs(false);
    const stepUpWithFactor = vi.fn();
    await mount({ auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    // A code box is no use to somebody who has nothing to type into it.
    await waitFor(() => {
      expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /set one up/i })).toHaveAttribute(
      "href",
      "/profile/security"
    );
  });

  it("offers both ways on when the status cannot be read", async () => {
    // A failed status query knows nothing, so the form stays for the enrolled
    // majority and the way to get a factor is offered beside it.
    server.use(http.get("/api/v1/auth/totp", () => HttpResponse.error()));
    await mount({ auth: { stepUpWithFactor: vi.fn() } });

    fireChallenge();
    await screen.findByRole("dialog");

    expect(await screen.findByLabelText(/authentication code/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /set one up/i })).toBeInTheDocument();
    });
  });

  it("opens once when a page's many requests are all refused", async () => {
    statusIs(true);
    await mount();

    fireChallenge({ communityId: 4 });
    fireChallenge({ communityId: 4 });
    fireChallenge({ communityId: 4 });

    await screen.findByRole("dialog");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("dismisses without stepping up", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn();
    await mount({ auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /not now/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(stepUpWithFactor).not.toHaveBeenCalled();
  });
});

describe("SecondFactorStepUpDialog, asked for a passkey", () => {
  it("offers the passkey rather than a code box", async () => {
    passkeysAre([{ id: "pk-1", name: "Laptop" }]);
    await mount({ auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
  });

  // What the presented passkey does to the session — the token it produces
  // becoming this browser's, and the account being read back under it — is the
  // hook's, proved in `src/hooks/useAuth.test.tsx`.
  it("closes on a presented passkey rather than making them reload", async () => {
    passkeysAre([{ id: "pk-1", name: "Laptop" }]);
    await mount({ auth: { stepUpWithPasskey: vi.fn().mockResolvedValue(undefined) } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");
    await userEvent.click(await screen.findByRole("button", { name: /use your passkey/i }));

    // The page behind it carries on rather than needing a reload.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("sends an account holding none to add one", async () => {
    passkeysAre([]);
    const stepUpWithPasskey = vi.fn();
    await mount({ auth: { stepUpWithPasskey } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("link", { name: /add a passkey/i })).toHaveAttribute(
      "href",
      "/profile/security"
    );
    expect(screen.queryByRole("button", { name: /use your passkey/i })).not.toBeInTheDocument();
  });

  it("keeps the passkey on offer when the account cannot be read", async () => {
    server.use(http.get("/api/v1/auth/passkeys", () => HttpResponse.error()));
    await mount({ auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(screen.getByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /add a passkey/i })).toBeInTheDocument();
    });
  });

  it("offers the key in the app too", async () => {
    passkeysAre([{ id: "pk-1", name: "Phone" }]);
    const stepUpWithPasskey = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithPasskey }, server: { isNativePlatform: true } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    await userEvent.click(await screen.findByRole("button", { name: /use your passkey/i }));
    expect(stepUpWithPasskey).toHaveBeenCalledTimes(1);
  });
});

/**
 * A change to how the account itself signs in wants a session opened a moment
 * ago. Presenting a passkey opens one; for an account that holds none, only
 * starting the sign-in over does.
 */
describe("SecondFactorStepUpDialog, asked to prove it's you", () => {
  it("offers the passkey the account already holds", async () => {
    passkeysAre([{ id: "pk-1", name: "Laptop" }]);
    const stepUpWithPasskey = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithPasskey } });

    fireChallenge({ communityId: null, kind: "proof" });
    await screen.findByRole("dialog");

    expect(screen.getByText(/prove it's you/i)).toBeInTheDocument();
    expect(screen.getByText(/present your passkey/i)).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: /use your passkey/i }));

    await waitFor(() => {
      expect(stepUpWithPasskey).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("confirms with a code sent to the account's address, where the deployment sends them", async () => {
    passkeysAre([]);
    server.use(
      http.get("/api/v1/config", () => HttpResponse.json({ login_methods: ["sso", "email_otp"] })),
      http.post("/api/v1/auth/step-up/email-otp/send", () =>
        HttpResponse.json({ status: "sent", challenge: "handle-1" })
      )
    );
    const stepUpWithEmailCode = vi.fn().mockResolvedValue(undefined);
    await mount({ auth: { stepUpWithEmailCode, stepUpWithPasskey: vi.fn() } });

    fireChallenge({ communityId: null, kind: "proof" });
    await screen.findByRole("dialog");
    await userEvent.click(await screen.findByRole("button", { name: /email me a code/i }));
    await userEvent.type(await screen.findByLabelText(/code from your email/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithEmailCode).toHaveBeenCalledWith({ challenge: "handle-1", code: "123456" });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("asks an account holding none to sign in again", async () => {
    passkeysAre([]);
    await mount({ auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ communityId: null, kind: "proof" });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("button", { name: /sign in again/i })).toBeInTheDocument();
    expect(screen.getByText(/sign out and back in/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /use your passkey/i })).not.toBeInTheDocument();
  });

  it("keeps both ways open when the account cannot be read", async () => {
    server.use(http.get("/api/v1/auth/passkeys", () => HttpResponse.error()));
    await mount({ auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ communityId: null, kind: "proof" });
    await screen.findByRole("dialog");

    expect(screen.getByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign in again/i })).toBeInTheDocument();
    });
  });

  it("signs out and returns them to the page they were on", async () => {
    passkeysAre([]);
    const logout = vi.fn().mockResolvedValue(undefined);
    const { router } = await mount({
      auth: { logout, stepUpWithPasskey: vi.fn() },
      initialRoute: "/profile/security",
    });

    fireChallenge({ communityId: null, kind: "proof" });
    await screen.findByRole("dialog");
    await userEvent.click(await screen.findByRole("button", { name: /sign in again/i }));

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    expect((router.state.location.search as { next?: string }).next).toBe("/profile/security");
  });
});

describe("when the deployment is the one asking", () => {
  it("says so, and offers the way out rather than a way past", async () => {
    // A refusal from the deployment is every request, not one page's, so
    // carrying on is not on offer — answering it or leaving is.
    statusIs(true);
    passkeysAre([]);
    await mount();

    fireChallenge({ communityId: null, platform: true });
    await screen.findByRole("dialog");

    expect(screen.getByText(/this server requires a second factor/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^dismiss$/i })).not.toBeInTheDocument();
  });

  it("offers the passkey the account already holds", async () => {
    // A user-verified passkey records the second factor too, so an account
    // with a key and no authenticator app has already met the rule and only
    // has to present it.
    statusIs(false);
    passkeysAre([{ id: "p1", name: "Laptop" }]);
    await mount({ auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ communityId: null, platform: true });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
  });

  it("holds off while the person is on the page that answers it", async () => {
    // The shell around that page makes requests of its own, and each would
    // put the dialog back over the thing it is asking them to do.
    statusIs(false);
    passkeysAre([]);
    await mount({ initialRoute: "/profile/security" });

    fireChallenge({ communityId: null, platform: true });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

/**
 * The Privacy tab.
 *
 * The two worth keeping are about the age question, which gates every one of
 * these controls on every deployment: an account that has not answered it can
 * choose no policy, and is told why rather than left with a dead radio group.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

import { PrivacyPage } from "./PrivacyPage";

const mocks = vi.hoisted(() => ({
  settings: vi.fn(),
  update: vi.fn(),
  connections: vi.fn(),
  messages: vi.fn(),
  ignored: vi.fn(),
  ignoreByHandle: vi.fn(),
  noop: vi.fn(),
  updateMe: vi.fn(),
  sections: vi.fn(),
}));

vi.mock("@/hooks/usePrivacySections", () => ({ usePrivacySections: () => mocks.sections() }));

// The write answers with the account as saved, the way the server does.
vi.mock("@/hooks/useUsers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useUsers")>()),
  useUpdateCurrentUser: (options?: { onSuccess?: (saved: UserRead, vars: unknown) => void }) => ({
    mutate: (vars: Partial<UserRead>) => {
      mocks.updateMe(vars);
      options?.onSuccess?.({ ...buildUser(), ...vars } as UserRead, vars);
    },
    isPending: false,
  }),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useDirectMessages")>()),
  useDmSettings: () => mocks.settings(),
  useUpdateDmSettings: () => ({ mutate: mocks.update, isPending: false }),
  useConnections: () => mocks.connections(),
  useMessageRequests: () => mocks.messages(),
  useIgnoredAccounts: () => mocks.ignored(),
  useRequestConnection: () => ({ mutateAsync: mocks.noop, isPending: false }),
  useRemoveConnection: () => ({ mutate: mocks.noop, isPending: false }),
  useAcceptConnection: () => ({ mutate: mocks.noop, isPending: false }),
  useAcceptMessageRequest: () => ({ mutate: mocks.noop, isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: mocks.noop, isPending: false }),
  useStopIgnoring: () => ({ mutate: mocks.noop, isPending: false }),
  useIgnoreAccountByHandle: () => ({ mutateAsync: mocks.ignoreByHandle, isPending: false }),
}));

const dmSettings = (overrides: Record<string, unknown> = {}) => ({
  data: {
    dm_policy: "private",
    age_confirmed_at: "2026-01-01T00:00:00Z",
    age_answer_required: false,
    communities: [{ community_id: 1, name: "Ravenloft Table", icon_url: null, enabled: true }],
    ...overrides,
  },
  isLoading: false,
});

describe("PrivacyPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.settings.mockReturnValue(dmSettings());
    mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
    mocks.messages.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
    mocks.ignored.mockReturnValue({ data: { items: [], total: 0 } });
    mocks.sections.mockReturnValue({ messages: true, ranking: true, cookies: false, any: true });
  });

  it("shows each section only where it has something to set", async () => {
    mocks.sections.mockReturnValue({ messages: false, ranking: true, cookies: false, any: true });
    const { unmount } = renderPage(PrivacyPage);

    expect(await screen.findByRole("switch", { name: /count my activity/i })).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    unmount();

    mocks.sections.mockReturnValue({ messages: true, ranking: false, cookies: false, any: true });
    renderPage(PrivacyPage);

    expect(await screen.findByRole("radio", { name: /private/i })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /count my activity/i })).not.toBeInTheDocument();
  });

  it.each([true, false])(
    "turns counting toward search ranking %s → the other way, and keeps what was saved",
    async (counted) => {
      const user = userEvent.setup();
      const acceptUser = vi.fn();
      renderPage(PrivacyPage, {
        auth: { user: buildUser({ count_toward_engagement_ranking: counted }), acceptUser },
      });

      const ranking = await screen.findByRole("switch", { name: /count my activity/i });
      expect(ranking).toHaveAttribute("aria-checked", String(counted));
      await user.click(ranking);

      expect(mocks.updateMe).toHaveBeenCalledWith({ count_toward_engagement_ranking: !counted });
      expect(acceptUser).toHaveBeenCalledWith(
        expect.objectContaining({ count_toward_engagement_ranking: !counted })
      );
    }
  );

  it("offers the three options the rule has, and nothing else", async () => {
    renderPage(PrivacyPage);

    expect(await screen.findByRole("radio", { name: /private/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /communities/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /anyone/i })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("locks the policy and says why until the age question is answered", async () => {
    mocks.settings.mockReturnValue(
      dmSettings({ age_confirmed_at: null, age_answer_required: true })
    );

    renderPage(PrivacyPage);

    expect(await screen.findByText(/16 and over/i)).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
  });

  it("takes the answer here, rather than pointing somewhere else for it", async () => {
    // This tab is where somebody comes to change who may reach them, and the
    // age question gates all of it. A notice saying the controls are locked,
    // with the key on another page, is not an answer.
    mocks.settings.mockReturnValue(
      dmSettings({ age_confirmed_at: null, age_answer_required: true })
    );

    renderPage(PrivacyPage);

    expect(await screen.findByLabelText(/date of birth/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm/i })).toBeInTheDocument();
  });

  it("asks nothing where the deployment does not check age", async () => {
    mocks.settings.mockReturnValue(dmSettings({ age_confirmed_at: null }));

    renderPage(PrivacyPage);

    expect(await screen.findByRole("radio", { name: /anyone/i })).toBeEnabled();
    expect(screen.queryByLabelText(/date of birth/i)).not.toBeInTheDocument();
  });

  it("shows the community toggles only under My communities", async () => {
    renderPage(PrivacyPage);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    mocks.settings.mockReturnValue(dmSettings({ dm_policy: "community" }));
    renderPage(PrivacyPage);

    expect(await screen.findByRole("switch", { name: /ravenloft/i })).toBeInTheDocument();
  });

  it("writes only the half that changed", async () => {
    renderPage(PrivacyPage);

    await userEvent.click(await screen.findByRole("radio", { name: /anyone/i }));

    expect(mocks.update).toHaveBeenCalledWith({ data: { dm_policy: "public" } }, expect.anything());
  });

  it("says nothing about who ignored whom", async () => {
    mocks.ignored.mockReturnValue({
      data: {
        items: [
          {
            user_id: 7,
            username: "bram",
            discriminator: 4410,
            avatar_url: null,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
      },
    });

    renderPage(PrivacyPage);

    // The list is the holder's own, and the copy stays on what it does for
    // them — never on what the other account can tell.
    const ignored = await screen.findByText(/bram/i);
    expect(ignored).toBeInTheDocument();
    expect(screen.queryByText(/they will not know/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/notified that/i)).not.toBeInTheDocument();
  });

  it("ignores somebody by their handle", async () => {
    mocks.ignoreByHandle.mockResolvedValue(undefined);
    renderPage(PrivacyPage);

    const field = await screen.findByRole("textbox", { name: /ignore by handle/i });
    await userEvent.type(field, "bram#4410{Enter}");

    expect(mocks.ignoreByHandle).toHaveBeenCalledWith({
      data: { username: "bram", discriminator: 4410 },
    });
    expect(field).toHaveValue("");
  });

  it("drops a handle's error once the handle changes", async () => {
    renderPage(PrivacyPage);

    const field = await screen.findByRole("textbox", { name: /ignore by handle/i });
    await userEvent.type(field, "bram{Enter}");
    expect(field).toHaveAttribute("aria-invalid", "true");

    await userEvent.type(field, "#4410");
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(mocks.ignoreByHandle).not.toHaveBeenCalled();
  });
});

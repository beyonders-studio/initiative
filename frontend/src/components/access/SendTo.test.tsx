import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser, buildUserPublic } from "@/__tests__/factories/user.factory";
import { renderPage } from "@/__tests__/helpers/render";
import type { ContentKind } from "@/api/generated/initiativeAPI.schemas";

const alice = buildUserPublic({ id: 101, display_name: "Alice" });
// The sender, signed in, and as the search lists them.
const me = buildUser({ id: 100 });
const meListed = buildUserPublic({ id: 100, display_name: "Me" });

// The initiative's people, searched on the server; the sender is among them.
const memberSearch = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useUsers", () => ({
  useMemberSearch: (scope: unknown, options: unknown) => {
    memberSearch(scope, options);
    return { data: { items: [meListed, alice] }, isFetching: false };
  },
}));

// Where the sender stands on what decides the thing, and the send itself.
const standing = vi.hoisted(() => ({ level: "owner" as string | null }));
const mutate = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useShareRequests", () => ({
  useShareStanding: () => ({
    data: { resource_type: "project", resource_id: 3, initiative_id: 5, level: standing.level },
  }),
  useSendTo: () => ({ mutate, isPending: false }),
}));

import { SendToDialog } from "./SendTo";

/** Mounts the dialog in a router, which the link it copies reads, and waits for it. */
const renderDialog = async (
  props: { kind: ContentKind; entityId: number },
  options: Parameters<typeof renderPage>[1] = {}
) => {
  renderPage(() => <SendToDialog open onOpenChange={vi.fn()} {...props} />, {
    auth: { user: me },
    ...options,
  });
  await screen.findByRole("dialog");
};

const pickAlice = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("combobox", { name: "People" }));
  await user.click(await screen.findByText("Alice"));
};

describe("SendToDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    standing.level = "owner";
  });

  it("sends to the people picked, letting them in at the rung chosen, with the note", async () => {
    const user = userEvent.setup();
    await renderDialog({ kind: "task", entityId: 7 });

    await pickAlice(user);
    await user.click(screen.getByRole("radio", { name: "Edit" }));
    await user.type(screen.getByRole("textbox", { name: "Note" }), "For Thursday");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith({
      kind: "task",
      entity_id: 7,
      user_ids: [101],
      note: "For Thursday",
      level: "write",
    });
    // The thing's initiative is whose people are offered, the sender left out.
    expect(memberSearch).toHaveBeenCalledWith(
      { type: "initiative", initiativeId: 5 },
      expect.anything()
    );
    expect(screen.queryByText("Me")).not.toBeInTheDocument();
  });

  it("lets nobody in for a sender who may not share it", async () => {
    standing.level = "read";
    const user = userEvent.setup();
    await renderDialog({ kind: "task", entityId: 7 });

    expect(screen.queryByRole("radio", { name: "Edit" })).not.toBeInTheDocument();
    await pickAlice(user);
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ level: null, note: null }));
  });

  // A tool plug-in's row's link is a built-in item's.
  it.each<[ContentKind, number]>([
    ["task", 7],
    ["counter.tsjvtcm0s7gv2x" as ContentKind, 9],
  ])(
    "copies the link the bell opens to %s %i, on the server the app is signed in to",
    async (kind, entityId) => {
      const user = userEvent.setup();
      await renderDialog(
        { kind, entityId },
        {
          communities: { activeCommunityId: 4 },
          server: { getServerOrigin: () => "https://initiative.example.com" },
        }
      );

      await user.click(screen.getByRole("button", { name: "Copy link" }));

      expect(await navigator.clipboard.readText()).toBe(
        `https://initiative.example.com/c/4/go/${kind}/${entityId}`
      );
    }
  );
});

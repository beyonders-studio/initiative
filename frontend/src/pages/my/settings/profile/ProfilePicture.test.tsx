/**
 * The picture is its own control, so the field behind it has to follow what is
 * actually saved — a URL left over from before an upload would be written back
 * over that upload the next time the tab was saved.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";

import { ProfilePicture } from "./ProfilePicture";

const mocks = vi.hoisted(() => ({ update: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({ useUpdateCurrentUser: () => mocks.update() }));

const BARE: ProfileDecorationsOutput = {
  banner: null,
  frame: null,
  frame_tint: [],
  trophies: [],
  grad_year: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.update.mockReturnValue({ mutate: vi.fn(), isPending: false });
});

const render = (user: ReturnType<typeof buildUser>) =>
  renderWithProviders(
    <ProfilePicture user={user} decorations={BARE} editable className="size-24" />
  );

describe("the picture editor", () => {
  const openEditor = async () =>
    userEvent.click(await screen.findByRole("button", { name: /avatar/i }));

  it("offers the linked URL it is actually wearing", async () => {
    render(buildUser({ avatar_url: "https://elsewhere.example/me.png" }));
    await openEditor();

    expect(screen.getByDisplayValue("https://elsewhere.example/me.png")).toBeInTheDocument();
  });

  it("forgets that URL once a picture has been uploaded over it", async () => {
    const linked = buildUser({ avatar_url: "https://elsewhere.example/me.png" });
    const { rerender } = render(linked);

    // The upload writes immediately, and the account comes back pointing at it.
    rerender(
      <ProfilePicture
        user={{ ...linked, avatar_url: "/api/v1/users/3/avatar" }}
        decorations={BARE}
        editable
        className="size-24"
      />
    );
    await openEditor();

    // Left behind, it is what the URL tab would write back over the upload.
    expect(screen.queryByDisplayValue("https://elsewhere.example/me.png")).not.toBeInTheDocument();
  });
});

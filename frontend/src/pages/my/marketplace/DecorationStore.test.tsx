/**
 * The store offers packs, and taking one is what puts its pieces in reach.
 *
 * What is worth pinning here is the tolerance — the server decides what packs
 * exist, and a build with no artwork for one must leave it out rather than draw
 * an empty card — and that a card, which can only show one piece per slot, can
 * be opened for the rest.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { DecorationStore } from "./DecorationStore";

const mocks = vi.hoisted(() => ({ packs: vi.fn(), install: vi.fn(), remove: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({
  useDecorationPacks: () => mocks.packs(),
  useInstallDecorationPack: (options: unknown) => mocks.install(options),
  useRemoveDecorationPack: (options: unknown) => mocks.remove(options),
}));

const listing = (
  uid: string,
  { installed = false, ids = ["ttrpg.dicetower", "ttrpg.natural20", "ttrpg.d20"] } = {}
) => ({
  uid,
  public_id: "core.tabletop",
  name: "Tabletop",
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: ids[0], kind: "banner", name: "Dice tower", source: uid },
    { id: ids[1], kind: "frame", name: "Natural 20", source: uid },
    { id: ids[2], kind: "trophy", name: "d20", source: uid },
  ],
});

const ttrpg = (installed = false) => listing("PACKTABTP00001", { installed });

const answerWith = (items: unknown[]) =>
  mocks.packs.mockReturnValue({ data: { items }, isLoading: false });

const installMutate = vi.fn();
const removeMutate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocks.install.mockReturnValue({ mutate: installMutate, isPending: false, variables: undefined });
  mocks.remove.mockReturnValue({ mutate: removeMutate, isPending: false, variables: undefined });
  answerWith([ttrpg()]);
});

const render = () => renderWithProviders(<DecorationStore user={buildUser()} />);

describe("the decoration store", () => {
  it("shows a pack by its name and what it is for", async () => {
    render();

    // The words are the listing's — its publisher named it, and nobody else
    // can name a pack published tomorrow.
    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText("Dice, and the people who roll them.")).toBeInTheDocument();
  });

  it("takes a pack when asked", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: "Get this pack" }));

    expect(installMutate).toHaveBeenCalledWith("PACKTABTP00001");
  });

  it("marks a pack already held rather than offering it again", async () => {
    answerWith([ttrpg(true)]);
    render();

    expect(await screen.findByText("In your collection")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get this pack" })).not.toBeInTheDocument();
  });

  it("gives a pack back from the card it was taken from", async () => {
    // Browsing is enough to change your mind: you found it here, so this is
    // where you look to be rid of it.
    answerWith([ttrpg(true)]);
    render();

    await userEvent.click(await screen.findByRole("button", { name: "Remove Tabletop" }));

    // Asked first, because the pieces go with it.
    expect(await screen.findByText("Remove Tabletop?")).toBeInTheDocument();
    expect(removeMutate).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Remove pack" }));

    expect(removeMutate).toHaveBeenCalledWith("PACKTABTP00001");
  });

  it("leaves out a pack this build has no artwork for", async () => {
    // A later catalog, an older client. An empty card would be worse than none.
    answerWith([
      ttrpg(),
      listing("PACKUNKNWN0001", {
        ids: ["studio.a", "studio.b", "studio.c"],
      }),
    ]);
    render();

    await screen.findByRole("heading", { name: "Tabletop" });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("says so when the build ships no packs at all", async () => {
    answerWith([]);
    render();

    await waitFor(() => expect(screen.getByText("No packs in this build.")).toBeInTheDocument());
  });
});

describe("what a pack carries", () => {
  it("opens the whole of it from the card", async () => {
    answerWith([ttrpg()]);
    renderWithProviders(<DecorationStore user={buildUser()} />);

    await userEvent.click(await screen.findByRole("button", { name: /Tabletop/ }));

    // Every piece, under the slot it goes in — not just the first of each.
    const contents = await screen.findByRole("dialog");
    expect(within(contents).getByText("Dice tower")).toBeInTheDocument();
    expect(within(contents).getByText("Natural 20")).toBeInTheDocument();
    expect(within(contents).getByText("d20")).toBeInTheDocument();
  });

  it("says how many pieces are in one before it is opened", async () => {
    answerWith([ttrpg()]);
    renderWithProviders(<DecorationStore user={buildUser()} />);

    expect(await screen.findByText("3 pieces")).toBeInTheDocument();
  });
});

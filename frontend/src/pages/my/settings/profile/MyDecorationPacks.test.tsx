/**
 * The packs you have: what each gave you, and the way out.
 *
 * This is the half of the store that answers "what do I have" — so what is
 * worth pinning is that it shows only downloaded packs, names their pieces,
 * is the one place removal happens, and stays usable once there are more packs
 * than fit on a screen.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MyDecorationPacks } from "./MyDecorationPacks";

const mocks = vi.hoisted(() => ({ packs: vi.fn(), remove: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({
  useDecorationPacks: () => mocks.packs(),
  useRemoveDecorationPack: (options: unknown) => mocks.remove(options),
}));

const entry = (uid: string, installed: boolean, { name = "Tabletop", slug = "ttrpg" } = {}) => ({
  uid,
  public_id: `core.${slug}`,
  name,
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: `${slug}.dicetower`, kind: "banner", name: "Dice tower", source: uid },
    { id: `${slug}.natural20`, kind: "frame", name: "Natural 20", source: uid },
    { id: `${slug}.d20`, kind: "trophy", name: "d20", source: uid },
  ],
});

const answerWith = (items: unknown[]) =>
  mocks.packs.mockReturnValue({ data: { items }, isLoading: false });

const removeMutate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocks.remove.mockReturnValue({ mutate: removeMutate, isPending: false, variables: undefined });
});

describe("the packs you have", () => {
  it("lists a downloaded pack and names its pieces", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText("Tabletop")).toBeInTheDocument();
    expect(screen.getByText("Dice tower")).toBeInTheDocument();
    expect(screen.getByText("Natural 20")).toBeInTheDocument();
    expect(screen.getByText("d20")).toBeInTheDocument();
  });

  it("leaves out a pack that has not been downloaded", async () => {
    answerWith([
      entry("PACKTABTP00001", true),
      entry("PACKBAND000001", false, { name: "Soundcheck", slug: "music" }),
    ]);
    renderWithProviders(<MyDecorationPacks />);

    await screen.findByText("Tabletop");
    expect(screen.queryByText("Soundcheck")).not.toBeInTheDocument();
  });

  it("asks before removing a pack, and names it in the asking", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    await userEvent.click(await screen.findByRole("button", { name: "Remove Tabletop" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Remove Tabletop\?/)).toBeInTheDocument();
    expect(removeMutate).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Remove pack" }));
    expect(removeMutate).toHaveBeenCalledWith("PACKTABTP00001");
  });

  it("keeps the pack when the asking is declined", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    await userEvent.click(await screen.findByRole("button", { name: "Remove Tabletop" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(removeMutate).not.toHaveBeenCalled();
  });

  it("offers a filter only once there are more packs than can be scanned", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    const { rerender } = renderWithProviders(<MyDecorationPacks />);

    await screen.findByText("Tabletop");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();

    answerWith(
      Array.from({ length: 12 }, (_, i) =>
        entry(`PACK${String(i).padStart(10, "0")}`, true, { name: `Pack ${i}` })
      )
    );
    rerender(<MyDecorationPacks />);

    await userEvent.type(await screen.findByRole("searchbox"), "Pack 7");
    expect(screen.getByText("Pack 7")).toBeInTheDocument();
    expect(screen.queryByText("Pack 3")).not.toBeInTheDocument();
  });

  it("points at the marketplace when nothing has been downloaded", async () => {
    answerWith([entry("PACKTABTP00001", false)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText(/marketplace is where you get them/)).toBeInTheDocument();
  });
});

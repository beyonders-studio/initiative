/**
 * The pickers offer a library, not a catalog.
 *
 * What a person may wear is the server's answer, and these render it: one
 * picker per slot, showing what that account has and nothing else. The rules
 * worth pinning are the ones a reader would notice — a slot holds one thing,
 * the trophy row holds several up to a cap, and a decoration this build has no
 * artwork for is left out rather than drawn as a blank tile.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildOwnedDecoration } from "@/__tests__/factories";

import { SlotPicker, TrophyPicker } from "./DecorationPicker";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}:${JSON.stringify(options)}` : key,
  }),
}));

const banners = [
  buildOwnedDecoration({ id: "core.aurora", kind: "banner" }),
  buildOwnedDecoration({ id: "core.ember", kind: "banner" }),
];

const trophies = [
  buildOwnedDecoration({ id: "ttrpg.d20", kind: "trophy" }),
  buildOwnedDecoration({ id: "plants.morel", kind: "trophy" }),
];

describe("a slot that holds one thing", () => {
  it("offers what the library holds for that slot, and nothing from another", async () => {
    render(
      <SlotPicker
        kind="banner"
        value={null}
        onChange={vi.fn()}
        owned={[
          ...banners,
          buildOwnedDecoration({ id: "core.gold", kind: "frame" }),
          // A pack the server knows about and this build has no artwork for. A
          // tile that renders as nothing is worse than no tile.
          buildOwnedDecoration({ id: "studio.holo", kind: "banner" }),
        ]}
      />
    );

    // Real radios sharing a name: the browser gives the group one tab stop and
    // arrow keys move within it, which is what a slot holding one thing means.
    const tiles = screen.getAllByRole("radio");
    expect(tiles).toHaveLength(2);
    for (const tile of tiles) {
      expect(tile).toHaveAttribute("name", "decoration-banner");
    }
    expect(screen.getByRole("radio", { name: "decorations.aurora" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "decorations.gold" })).not.toBeInTheDocument();
  });

  it("takes the decoration off when the one already on is picked again", async () => {
    const onChange = vi.fn();
    render(<SlotPicker kind="banner" value="core.aurora" onChange={onChange} owned={banners} />);

    const chosen = screen.getByRole("radio", { name: "decorations.aurora" });
    expect(chosen).toBeChecked();
    await userEvent.click(chosen);

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says so when the library has nothing for the slot", () => {
    render(<SlotPicker kind="frame" value={null} onChange={vi.fn()} owned={banners} />);

    expect(screen.getByText("decorationPicker.empty")).toBeInTheDocument();
  });
});

describe("the trophy row", () => {
  it.each([
    [["plants.morel"], ["plants.morel", "ttrpg.d20"]],
    [["ttrpg.d20"], []],
  ])(
    "wears them in the order picked, and takes one off when picked again (%j)",
    async (value, next) => {
      const onChange = vi.fn();
      render(<TrophyPicker value={value} onChange={onChange} owned={trophies} max={6} />);

      await userEvent.click(screen.getByRole("checkbox", { name: "decorations.d20" }));

      expect(onChange).toHaveBeenCalledWith(next);
    }
  );

  it("marks a tile past the cap as unavailable, rather than dropping what is worn", async () => {
    // Disabled says "not now" to a screen reader; an unresponsive tile says
    // nothing at all. What is on is the reader's choice; the picker must not
    // quietly evict the oldest trophy to make room for a new one.
    const onChange = vi.fn();
    render(<TrophyPicker value={["plants.morel"]} onChange={onChange} owned={trophies} max={1} />);

    const d20 = screen.getByRole("checkbox", { name: "decorations.d20" });
    expect(d20).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "decorations.morel" })).toBeEnabled();
    await userEvent.click(d20);
    expect(onChange).not.toHaveBeenCalled();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ColorPickerPopover } from "./color-picker-popover";

/**
 * A caller that previews as you pick — it moves its own state from `onChange`,
 * so the picker's `value` catches up with the draft while the popover is still
 * open, and only writes the colour down when the popover closes. The community
 * banner's fill is one of these.
 */
const LivePreview = () => {
  const [color, setColor] = useState("#000000");
  const [saved, setSaved] = useState<string[]>([]);
  return (
    <>
      <ColorPickerPopover
        value={color}
        onChange={setColor}
        onChangeComplete={(next) => setSaved((all) => [...all, next])}
        triggerLabel="Banner fill"
      />
      <output data-testid="saved">{saved.join(",")}</output>
    </>
  );
};

const pickHex = async (hex: string) => {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Banner fill" }));
  const hexField = screen.getByDisplayValue("#000000");
  await user.clear(hexField);
  await user.type(hexField, hex);
  // The hex field takes the value on blur, as it does for a real typist.
  await user.tab();
  return user;
};

describe("ColorPickerPopover", () => {
  it("commits a live-previewed colour when the popover closes", async () => {
    render(<LivePreview />);

    const user = await pickHex("#2A9D8F");
    await user.keyboard("{Escape}");

    expect(await screen.findByTestId("saved")).toHaveTextContent("#2A9D8F");
  });

  it("opens on black as black, not as red", async () => {
    // Black is 0,0,0 — a saturation and a lightness the picker used to read as
    // "unset" and replace with its defaults, which is red.
    const user = userEvent.setup();
    render(<LivePreview />);

    await user.click(screen.getByRole("button", { name: "Banner fill" }));

    expect(await screen.findByDisplayValue("#000000")).toBeInTheDocument();
    expect(screen.getByTestId("saved")).toHaveTextContent("");
  });

  it("commits nothing when the colour was left alone", async () => {
    render(<LivePreview />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Banner fill" }));
    await user.keyboard("{Escape}");

    expect(screen.getByTestId("saved")).toHaveTextContent("");
  });
});

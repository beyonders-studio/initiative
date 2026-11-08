import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

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
  const hexField = await screen.findByDisplayValue("#000000");
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

  it("reports nothing until the colour is changed", async () => {
    // A caller that previews live feeds each report back as the value, so a
    // report of its own value would go round again.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ColorPickerPopover value="#000000" onChange={onChange} triggerLabel="Fill" />);

    await user.click(screen.getByRole("button", { name: "Fill" }));
    await screen.findByDisplayValue("#000000");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("opens from a control of the caller's own, named by its label, and can be opaque", async () => {
    const user = userEvent.setup();
    render(
      <ColorPickerPopover value="#112233" opaque triggerLabel="Fill colour">
        <button type="button">A</button>
      </ColorPickerPopover>
    );

    await user.click(screen.getByRole("button", { name: "Fill colour" }));

    expect(await screen.findByDisplayValue("#112233")).toBeInTheDocument();
    // The hue, and no transparency.
    expect(screen.getAllByRole("slider")).toHaveLength(1);
  });

  it("commits nothing when the colour was left alone", async () => {
    render(<LivePreview />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Banner fill" }));
    await user.keyboard("{Escape}");

    expect(screen.getByTestId("saved")).toHaveTextContent("");
  });
});

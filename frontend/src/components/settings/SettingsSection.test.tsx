import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Switch } from "@/ui/switch";

import { SettingsRow } from "./SettingsSection";

const Toggle = () => {
  const [on, setOn] = useState(false);
  return (
    <SettingsRow label="Read receipts" description="Show people when you have read a message.">
      <Switch checked={on} onCheckedChange={setOn} />
    </SettingsRow>
  );
};

describe("SettingsRow", () => {
  it("names and describes its control", () => {
    render(<Toggle />);

    expect(screen.getByRole("switch", { name: "Read receipts" })).toHaveAccessibleDescription(
      "Show people when you have read a message."
    );
  });

  it("toggles its control when its label is clicked", async () => {
    const user = userEvent.setup();
    render(<Toggle />);

    await user.click(screen.getByText("Read receipts"));

    expect(screen.getByRole("switch", { name: "Read receipts" })).toBeChecked();
  });
});

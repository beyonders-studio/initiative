import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Field } from "./field";
import { SecretInput } from "./secret-input";

/** A form that holds what is typed, and clears it the way a save does. */
function Form({ saved, hint }: { saved: boolean; hint?: string }) {
  const [value, setValue] = useState("");
  return (
    <>
      <Field label="Client secret">
        <SecretInput saved={saved} hint={hint} value={value} onValueChange={setValue} />
      </Field>
      <button type="button" onClick={() => setValue("")}>
        Save
      </button>
    </>
  );
}

describe("SecretInput", () => {
  it("shows a saved secret by its hint, and opens a field to replace it", async () => {
    const user = userEvent.setup();
    render(<Form saved hint="SHA256:GWYACUkXdzZ4DZwX4wBX1eKLAzyM4DCskXNEAhmNKCs=" />);

    expect(screen.getByText("SHA256:GWYACUkXdzZ4DZwX4wBX1eKLAzyM4DCskXNEAhmNKCs=")).toBeVisible();
    expect(screen.getByText("Saved")).toBeVisible();

    await user.click(screen.getByLabelText("Client secret"));
    const field = screen.getByLabelText("Client secret");
    expect(field).toHaveFocus();
    await user.type(field, "n3w");

    // A save clears what was typed, and the saved secret shows again.
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Saved")).toBeVisible();
  });

  it("hides what is typed until asked to show it", async () => {
    const user = userEvent.setup();
    render(<Form saved={false} />);

    const field = screen.getByLabelText("Client secret");
    await user.type(field, "n3w");
    expect(field).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Show the secret" }));
    expect(field).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide the secret" }));
    expect(field).toHaveAttribute("type", "password");
  });
});

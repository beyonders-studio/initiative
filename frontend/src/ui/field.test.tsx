import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Combobox } from "./combobox";
import { Field } from "./field";
import { Input } from "./input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

describe("Field", () => {
  it("names the control it holds with its label", () => {
    render(
      <>
        <Field label="Name">
          <Input />
        </Field>
        <Field label="Status">
          <Select>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Owner">
          <Combobox items={[]} />
        </Field>
      </>
    );

    expect(screen.getByRole("textbox", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Owner" })).toBeInTheDocument();
  });

  it("describes the control with its hint and its error", () => {
    render(
      <Field label="Slug" hint="Lowercase letters only." error="That slug is taken.">
        <Input />
      </Field>
    );

    expect(screen.getByRole("textbox", { name: "Slug" })).toHaveAccessibleDescription(
      "Lowercase letters only. That slug is taken."
    );
  });

  it("marks the control invalid only while it has an error", () => {
    const { rerender } = render(
      <Field label="Slug">
        <Input />
      </Field>
    );
    expect(screen.getByRole("textbox", { name: "Slug" })).not.toBeInvalid();

    rerender(
      <Field label="Slug" error="That slug is taken.">
        <Input />
      </Field>
    );
    expect(screen.getByRole("textbox", { name: "Slug" })).toBeInvalid();
    expect(screen.getByRole("alert")).toHaveTextContent("That slug is taken.");
  });
});

/**
 * What the select reports as a choice.
 *
 * A task page moving to a task in another project swaps one project's status
 * columns for another's while the select stays mounted. The primitive answers
 * a value its options don't name by holding no selection and reporting the
 * empty string — which the status field read as a change to status 0, leaving
 * the field blank, the form permanently unsaved, and a save the API refused.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

const Columns = ({
  value,
  ids,
  onValueChange,
}: {
  value: string;
  ids: number[];
  onValueChange: (next: string) => void;
}) => (
  // Inside a form, like the task editor's status field: that is when the
  // primitive keeps the hidden native select which reports the empty value.
  <form>
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger>
        <SelectValue placeholder="Pick one" />
      </SelectTrigger>
      <SelectContent>
        {ids.map((id) => (
          <SelectItem key={id} value={String(id)}>
            Column {id}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  </form>
);

describe("Select", () => {
  it("does not report a choice when its options stop naming the value", () => {
    const onValueChange = vi.fn();
    const { rerender } = render(
      <Columns value="58" ids={[57, 58, 59, 60]} onValueChange={onValueChange} />
    );

    // The next task's status arrives before its project's columns do, so for
    // a beat the value names a column this list does not have.
    rerender(<Columns value="62" ids={[57, 58, 59, 60]} onValueChange={onValueChange} />);
    rerender(<Columns value="62" ids={[61, 62, 63, 64]} onValueChange={onValueChange} />);

    expect(onValueChange).not.toHaveBeenCalledWith("");
  });

  it("reports the column somebody picks", async () => {
    const onValueChange = vi.fn();
    render(<Columns value="62" ids={[61, 62, 63, 64]} onValueChange={onValueChange} />);

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "Column 63" }));

    expect(onValueChange).toHaveBeenCalledWith("63");
  });
});

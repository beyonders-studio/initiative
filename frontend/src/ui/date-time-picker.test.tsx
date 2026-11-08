import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { DateTimePicker } from "./date-time-picker";

const openPicker = async (includeTime = false) => {
  const onChange = vi.fn();
  renderWithProviders(
    <DateTimePicker
      value={includeTime ? "2026-01-01T09:00" : "2026-01-01"}
      onChange={onChange}
      includeTime={includeTime}
    />
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /jan 1, 2026/i }));
  return { onChange, input: screen.getByRole("textbox", { name: /type or pick a date/i }) };
};

describe("manual calendar entry", () => {
  it.each(["2026-02-30", "2025-02-29", "2026-04-31"])(
    "keeps invalid %s for correction without saving",
    async (value) => {
      const { onChange, input } = await openPicker();
      fireEvent.change(input, { target: { value } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onChange).not.toHaveBeenCalled();
      expect(input).toHaveValue(value);
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid calendar date");
      fireEvent.change(input, { target: { value: "2024-02-29" } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onChange).toHaveBeenCalledWith("2024-02-29");
    }
  );

  it.each(["2026-03-29 02:30", "2026-10-25 02:30"])(
    "explicitly rejects skipped/repeated local time %s",
    async (value) => {
      vi.stubEnv("TZ", "Europe/Amsterdam");
      const { onChange, input } = await openPicker(true);
      fireEvent.change(input, { target: { value } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(/skipped or repeated/i);
    }
  );
});

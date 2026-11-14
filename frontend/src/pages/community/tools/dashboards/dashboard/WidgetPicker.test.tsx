/**
 * Choosing a widget.
 *
 * Two things are load-bearing here. The list is *one* list — the old palette
 * split "ready-made" from "widgets" and said the same thing twice — and a widget
 * names itself: every row's label comes from the widget module's own `meta`, run
 * through the sandbox, which is what an installed listing will rely on. The
 * search reaches those names and the widget's own option labels, so "pie" finds
 * the chart that can draw one even though no row is called "pie chart".
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";

import { WidgetPicker } from "./WidgetPicker";

const catalog = {
  widgets: [
    {
      type: "chart",
      min_w: 3,
      min_h: 3,
      default_w: 6,
      default_h: 4,
      shape: [
        {
          name: "label",
          types: ["text", "enum", "reference", "date"],
          required: true,
          repeatable: false,
        },
        { name: "value", types: ["number"], required: true, repeatable: true },
      ],
      options: [
        { key: "mark", values: ["area", "bar", "line", "pie"], kind: "choice" },
        { key: "stacked", values: ["false", "true"], kind: "choice" },
      ],
    },
    {
      type: "stat",
      min_w: 2,
      min_h: 2,
      default_w: 3,
      default_h: 2,
      shape: [
        { name: "value", types: ["number"], required: true, repeatable: false },
        { name: "label", types: ["text", "enum", "reference"], required: false, repeatable: false },
      ],
      options: [
        { key: "format", values: ["currency", "duration", "percent", "plain"], kind: "choice" },
      ],
    },
  ],
  presets: [{ name: "bar_chart", primitive: "chart", options: { mark: "bar" } }],
} as unknown as WidgetCatalog;

const open = async (onAdd = vi.fn()) => {
  const user = userEvent.setup();
  renderWithProviders(<WidgetPicker catalog={catalog} widgetCount={0} onAdd={onAdd} />);
  await user.click(screen.getByRole("button", { name: /add widget/i }));
  // The names arrive from the widget modules, so the list is not readable until
  // the sandbox has answered.
  await screen.findByRole("button", { name: /^Stat/ });
  return { user, onAdd };
};

const list = () => screen.getByRole("list", { name: "Widgets" });

describe("WidgetPicker", () => {
  it("offers every widget in one list, named by the widget itself", async () => {
    await open();
    const rows = within(list()).getAllByRole("button");
    expect(rows.map((row) => row.textContent?.split(/(?=[A-Z])/)[0])).toHaveLength(2);
    expect(within(list()).getByRole("button", { name: /^Chart/ })).toBeInTheDocument();
    expect(within(list()).getByRole("button", { name: /^Stat/ })).toBeInTheDocument();
  });

  it("does not list presets separately from the widget they are made of", async () => {
    await open();
    // `bar_chart` is in the catalog; it must not appear as its own row, because
    // it is the chart widget with an option set — which the card offers.
    expect(within(list()).getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByText(/ready-made/i)).toBeNull();
  });

  it("searches the widget's own option labels, not just its name", async () => {
    const { user } = await open();
    await user.type(screen.getByRole("textbox"), "pie");

    // No widget is called "pie" — the chart declares it as a value of its
    // `mark` option, and that is what the search matched.
    await waitFor(() => expect(within(list()).getAllByRole("button")).toHaveLength(1));
    expect(within(list()).getByRole("button", { name: /^Chart/ })).toBeInTheDocument();
  });

  it("says so when nothing matches", async () => {
    const { user } = await open();
    await user.type(screen.getByRole("textbox"), "kanban");
    expect(await screen.findByText(/no widget matches/i)).toBeInTheDocument();
  });

  it("adds the selected widget bound to a statement, which is what a widget draws", async () => {
    const { user, onAdd } = await open();
    await user.click(within(list()).getByRole("button", { name: /^Chart/ }));
    await user.click(screen.getByRole("button", { name: /^Add Chart$/ }));

    // Not `counter_group`, which comes first alphabetically but would land the
    // widget on "choose what this shows".
    expect(onAdd).toHaveBeenCalledWith("chart", "query", undefined);
  });

  it("carries the display options chosen on the card", async () => {
    const { user, onAdd } = await open();
    await user.click(within(list()).getByRole("button", { name: /^Chart/ }));
    await user.click(screen.getByRole("button", { name: "Pie" }));
    await user.click(screen.getByRole("button", { name: /^Add Chart$/ }));

    expect(onAdd).toHaveBeenCalledWith("chart", "query", { mark: "pie" });
  });

  it("lets a chosen option be cleared back to the widget's own default", async () => {
    const { user, onAdd } = await open();
    await user.click(within(list()).getByRole("button", { name: /^Chart/ }));
    await user.click(screen.getByRole("button", { name: "Pie" }));
    await user.click(screen.getByRole("button", { name: "Pie" }));
    await user.click(screen.getByRole("button", { name: /^Add Chart$/ }));

    expect(onAdd).toHaveBeenCalledWith("chart", "query", undefined);
  });

  it("will not open at the widget cap", () => {
    renderWithProviders(<WidgetPicker catalog={catalog} widgetCount={50} onAdd={vi.fn()} />);
    expect(screen.getByRole("button", { name: /add widget/i })).toBeDisabled();
    // Disabled with no explanation is a dead end, so the cap is stated next to it.
    expect(screen.getByText(/can hold 50 widgets/i)).toBeInTheDocument();
  });
});

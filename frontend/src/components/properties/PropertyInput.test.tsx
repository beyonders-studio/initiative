import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildPropertyDefinition,
  buildPropertyOption,
  buildPropertySummary,
} from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MetadataType, type PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { PropertyInput } from "./PropertyInput";

const def = (overrides: Partial<PropertyDefinitionRead>) =>
  buildPropertyDefinition({ ...overrides });

describe("PropertyInput", () => {
  describe("text type", () => {
    it("renders an <input type='text'> and calls onChange with the string", async () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.text, name: "Owner" })}
          value=""
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("Empty") as HTMLInputElement;
      expect(input.type).toBe("text");
      await userEvent.type(input, "a");
      expect(onChange).toHaveBeenLastCalledWith("a");
    });
  });

  describe("number type", () => {
    it("renders an <input type='number'> and parses '42' into a number", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.number, name: "Count" })}
          value={null}
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("0") as HTMLInputElement;
      expect(input.type).toBe("number");
      // userEvent.type doesn't support fractional/full-value in a single call well
      // for type=number; fire change directly to mirror user entering 42.
      fireEvent.change(input, { target: { value: "42" } });
      expect(onChange).toHaveBeenCalledWith(42);
    });
  });

  describe("money type", () => {
    it("takes an amount and names the property's currency beside it", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.currency, name: "Price", currency: "EUR" })}
          value={null}
          onChange={onChange}
        />
      );
      expect(screen.getByText("EUR")).toBeInTheDocument();
      fireEvent.change(screen.getByPlaceholderText("0"), { target: { value: "12.5" } });
      expect(onChange).toHaveBeenCalledWith(12.5);
    });
  });

  describe("scale type", () => {
    it("takes a number, kept within 0 to 100", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.scale, name: "Score" })}
          value={null}
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("0–100");
      fireEvent.change(input, { target: { value: "140" } });
      expect(onChange).toHaveBeenLastCalledWith(100);
      fireEvent.change(input, { target: { value: "-5" } });
      expect(onChange).toHaveBeenLastCalledWith(0);
    });

    it("is set by stars, each a fifth, where it is drawn as stars", async () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.scale, name: "Score" })}
          value={61}
          onChange={onChange}
          display="stars"
        />
      );
      const stars = screen.getByRole("group", { name: "Score" });
      // 61 begins the fourth fifth.
      expect(within(stars).getByRole("button", { name: "4 stars" })).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      await userEvent.click(within(stars).getByRole("button", { name: "2 stars" }));
      expect(onChange).toHaveBeenCalledWith(40);
    });

    it("is set along a bar where it is drawn as one", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.scale, name: "Score" })}
          value={30}
          onChange={onChange}
          display="bar"
        />
      );
      const thumb = screen.getByRole("slider", { name: "Score" });
      expect(thumb).toHaveAttribute("aria-valuenow", "30");
      fireEvent.keyDown(thumb, { key: "ArrowRight" });
      expect(onChange).toHaveBeenCalledWith(31);
    });
  });

  describe("checkbox type", () => {
    it("renders a checkbox and toggles onChange(true)", async () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.checkbox, name: "Done" })}
          value={false}
          onChange={onChange}
        />
      );
      const checkbox = screen.getByRole("checkbox");
      await userEvent.click(checkbox);
      expect(onChange).toHaveBeenCalledWith(true);
    });
  });

  describe("date type", () => {
    it("renders a DateTimePicker (includeTime=false)", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.date, name: "Deadline" })}
          value=""
          onChange={vi.fn()}
        />
      );
      // DateTimePicker renders a button with "Pick a date" placeholder when no value.
      expect(screen.getByRole("button", { name: /pick a date/i })).toBeInTheDocument();
    });
  });

  describe("datetime type", () => {
    it("renders a DateTimePicker with time support", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.datetime, name: "When" })}
          value=""
          onChange={vi.fn()}
        />
      );
      expect(screen.getByRole("button", { name: /pick a date and time/i })).toBeInTheDocument();
    });
  });

  describe("url type", () => {
    it("renders an <input type='url'> and propagates the value", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.url, name: "Website" })}
          value=""
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("https://…") as HTMLInputElement;
      expect(input.type).toBe("url");
      fireEvent.change(input, { target: { value: "https://example.com" } });
      expect(onChange).toHaveBeenCalledWith("https://example.com");
    });
  });

  describe("select type", () => {
    const selectDef = def({
      type: MetadataType.select,
      name: "Status",
      options: [
        buildPropertyOption({ value: "draft", label: "Draft" }),
        buildPropertyOption({ value: "live", label: "Live" }),
      ],
    });

    it("renders the options and fires onChange with the option slug when picked", async () => {
      const onChange = vi.fn();
      renderWithProviders(<PropertyInput definition={selectDef} value="" onChange={onChange} />);
      // The new picker is a Popover-trigger button (not a Radix combobox).
      const trigger = screen.getByRole("button", { name: /Select/i });
      await userEvent.click(trigger);
      const liveOption = await screen.findByRole("option", { name: /Live/i });
      await userEvent.click(liveOption);
      expect(onChange).toHaveBeenCalledWith("live");
    });

    it("renders fallback 'Unknown option' text when value is not in definition.options", () => {
      renderWithProviders(
        <PropertyInput definition={selectDef} value="archived" onChange={vi.fn()} />
      );
      expect(screen.getByText(/Unknown option: archived/i)).toBeInTheDocument();
    });
  });

  describe("multi_select type", () => {
    it("renders a multi-select and emits an array of slugs on change", async () => {
      const multiDef = def({
        type: MetadataType.multi_select,
        name: "Tags",
        options: [
          buildPropertyOption({ value: "alpha", label: "Alpha" }),
          buildPropertyOption({ value: "beta", label: "Beta" }),
        ],
      });
      const onChange = vi.fn();
      renderWithProviders(<PropertyInput definition={multiDef} value={[]} onChange={onChange} />);
      const trigger = screen.getByRole("button", { name: /Select options/i });
      await userEvent.click(trigger);
      const alphaOption = await screen.findByRole("option", { name: /Alpha/i });
      await userEvent.click(alphaOption);
      expect(onChange).toHaveBeenCalledWith(["alpha"]);
    });
  });

  describe("user_reference type", () => {
    it("renders a user picker backed by the initiative-members search API", async () => {
      // The picker is scoped to the property's initiative (default id 1) and
      // fetches a slim, paginated UserSummary page when opened.
      server.use(
        communityHttp.get("/initiatives/:initiativeId/members/search", () =>
          HttpResponse.json({
            items: [
              {
                id: 7,
                display_name: "Ada Lovelace",
                avatar_url: null,
                status: "active",
              },
              {
                id: 8,
                display_name: "Grace Hopper",
                avatar_url: null,
                status: "active",
              },
            ],
            total_count: 2,
            page: 1,
            page_size: 25,
            has_next: false,
            has_prev: false,
          })
        )
      );
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.user_reference, name: "Owner" })}
          value={null}
          onChange={vi.fn()}
        />
      );
      const trigger = screen.getByRole("combobox");
      expect(trigger).toBeInTheDocument();
      // Members load and render in the popover only after it opens (enabled gate).
      await userEvent.click(trigger);
      await waitFor(() =>
        expect(screen.getByRole("option", { name: /Ada Lovelace/i })).toBeInTheDocument()
      );
    });
  });

  describe("disabled prop", () => {
    it("disables a text input", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.text })}
          value=""
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByPlaceholderText("Empty")).toBeDisabled();
    });

    it("disables a checkbox", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.checkbox })}
          value={false}
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByRole("checkbox")).toBeDisabled();
    });

    it("disables a select trigger", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({
            type: MetadataType.select,
            options: [buildPropertyOption({ value: "a", label: "A" })],
          })}
          value=""
          onChange={vi.fn()}
          disabled
        />
      );
      const trigger = screen.getByRole("button", { name: /Select/i });
      expect(trigger).toBeDisabled();
    });

    it("disables a number input", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: MetadataType.number })}
          value={null}
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByPlaceholderText("0")).toBeDisabled();
    });
  });

  describe("summary-shape definitions", () => {
    it("accepts a PropertySummary (no id/initiative_id) as definition", () => {
      renderWithProviders(
        <PropertyInput
          definition={buildPropertySummary({ name: "Lite", value: null })}
          value="hello"
          onChange={vi.fn()}
        />
      );
      expect(screen.getByDisplayValue("hello")).toBeInTheDocument();
    });
  });

  describe("select options rendering", () => {
    it("shows each option label in the dropdown", async () => {
      const multi = def({
        type: MetadataType.select,
        options: [
          buildPropertyOption({ value: "one", label: "One" }),
          buildPropertyOption({ value: "two", label: "Two" }),
        ],
      });
      renderWithProviders(<PropertyInput definition={multi} value="" onChange={vi.fn()} />);
      const trigger = screen.getByRole("button", { name: /Select/i });
      await userEvent.click(trigger);
      const listbox = await screen.findByRole("listbox");
      expect(within(listbox).getByRole("option", { name: /One/i })).toBeInTheDocument();
      expect(within(listbox).getByRole("option", { name: /Two/i })).toBeInTheDocument();
    });
  });

  describe("inline option creation on select", () => {
    it("offers a 'Create' command when typing a new label, and appends + selects it on click", async () => {
      const definition = def({
        id: 33,
        type: MetadataType.select,
        name: "Status",
        options: [buildPropertyOption({ value: "draft", label: "Draft" })],
      });
      const bodies: unknown[] = [];
      server.use(
        communityHttp.patch("/property-definitions/:id", async ({ request }) => {
          const body = await request.json();
          bodies.push(body);
          return HttpResponse.json({
            definition: { ...definition, options: (body as { options: unknown }).options },
            orphaned_value_count: 0,
          });
        })
      );
      const onChange = vi.fn();
      renderWithProviders(<PropertyInput definition={definition} value="" onChange={onChange} />);
      const trigger = screen.getByRole("button", { name: /Select/i });
      await userEvent.click(trigger);
      const searchBox = await screen.findByPlaceholderText(/Search or create/i);
      await userEvent.type(searchBox, "In Review");
      const createItem = await screen.findByRole("option", { name: /Create "In Review"/i });
      await userEvent.click(createItem);
      await waitFor(() => expect(bodies).toHaveLength(1));
      const patched = bodies[0] as { options: Array<{ value: string; label: string }> };
      expect(patched.options).toEqual([
        expect.objectContaining({ value: "draft", label: "Draft" }),
        expect.objectContaining({ value: "in_review", label: "In Review" }),
      ]);
      await waitFor(() => expect(onChange).toHaveBeenCalledWith("in_review"));
    });

    it("does NOT offer Create when the typed label matches an existing option (case-insensitive)", async () => {
      const definition = def({
        type: MetadataType.select,
        options: [buildPropertyOption({ value: "live", label: "Live" })],
      });
      renderWithProviders(<PropertyInput definition={definition} value="" onChange={vi.fn()} />);
      const trigger = screen.getByRole("button", { name: /Select/i });
      await userEvent.click(trigger);
      const searchBox = await screen.findByPlaceholderText(/Search or create/i);
      await userEvent.type(searchBox, "live");
      expect(screen.queryByRole("option", { name: /Create "live"/i })).not.toBeInTheDocument();
      expect(screen.getByRole("option", { name: /Live/i })).toBeInTheDocument();
    });
  });
});

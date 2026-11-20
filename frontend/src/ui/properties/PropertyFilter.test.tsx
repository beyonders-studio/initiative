import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition, buildPropertyOption } from "@/__tests__/factories/properties";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";

import { PropertyFilter, type PropertyFilterCondition } from "./PropertyFilter";

// What a value's input adds or looks up; none of these filters asks either.
const INPUT = {
  appendOption: vi.fn(),
  searchMembers: vi.fn(async () => []),
};

describe("PropertyFilter", () => {
  const textDef = buildPropertyDefinition({
    id: 1,
    name: "Owner",
    type: MetadataType.text,
  });
  const numberDef = buildPropertyDefinition({
    id: 2,
    name: "Hours",
    type: MetadataType.number,
  });
  const selectDef = buildPropertyDefinition({
    id: 3,
    name: "Status",
    type: MetadataType.select,
    options: [
      buildPropertyOption({ value: "draft", label: "Draft" }),
      buildPropertyOption({ value: "live", label: "Live" }),
    ],
  });

  it("renders nothing if there are no eligible definitions and no existing filters", () => {
    const { container } = renderWithProviders(
      <PropertyFilter {...INPUT} value={[]} definitions={[]} onChange={vi.fn()} />
    );
    expect(container.querySelector("button")).toBeNull();
  });

  it.each([
    [
      "a text property, matched loosely",
      () => textDef,
      { property_id: 1, op: "ilike", value: null },
    ],
    [
      "a multi_select, holding an empty array",
      () =>
        buildPropertyDefinition({
          id: 10,
          name: "Tags",
          type: MetadataType.multi_select,
          options: [buildPropertyOption({ value: "a", label: "A" })],
        }),
      { property_id: 10, op: "eq", value: [] },
    ],
  ])("adds a filter row on Add for %s", async (_case, definition, row) => {
    const onChange = vi.fn();
    renderWithProviders(
      <PropertyFilter {...INPUT} definitions={[definition()]} value={[]} onChange={onChange} />
    );
    const addBtn = await screen.findByRole("button", { name: /Add filter/i });
    expect(addBtn).toBeEnabled();
    await userEvent.click(addBtn);
    expect(onChange).toHaveBeenCalledWith([row], []);
  });

  it("caps the number of filters at the configured max (default 5)", async () => {
    const definitions = [
      textDef,
      numberDef,
      selectDef,
      buildPropertyDefinition({
        id: 4,
        name: "Extra",
        type: MetadataType.text,
      }),
      buildPropertyDefinition({
        id: 5,
        name: "Fifth",
        type: MetadataType.text,
      }),
      buildPropertyDefinition({
        id: 6,
        name: "Sixth",
        type: MetadataType.text,
      }),
    ];
    const full: PropertyFilterCondition[] = [
      { property_id: 1, op: "eq", value: "a" },
      { property_id: 2, op: "eq", value: 1 },
      { property_id: 3, op: "eq", value: "draft" },
      { property_id: 4, op: "eq", value: "x" },
      { property_id: 5, op: "eq", value: "y" },
    ];
    renderWithProviders(
      <PropertyFilter {...INPUT} definitions={definitions} value={full} onChange={vi.fn()} />
    );
    const addBtn = await screen.findByRole("button", { name: /Add filter/i });
    expect(addBtn).toBeDisabled();
  });

  it("resets op to the first valid op for the new type when the property dropdown changes", async () => {
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [{ property_id: 1, op: "ilike", value: "ada" }];
    renderWithProviders(
      <PropertyFilter
        {...INPUT}
        definitions={[textDef, numberDef]}
        value={existing}
        onChange={onChange}
      />
    );
    // The property dropdown is the first combobox in the row.
    const propertyCombo = (await screen.findAllByLabelText(/Filter by/i))[0];
    await userEvent.click(propertyCombo);
    const hoursOption = await screen.findByRole("option", { name: "Hours" });
    await userEvent.click(hoursOption);
    expect(onChange).toHaveBeenCalledWith(
      [
        {
          property_id: 2,
          op: "eq", // first op in opsForType(number) = "eq"
          value: null, // defaultValueForDefinition(number, "eq") = null
        },
      ],
      []
    );
  });

  it("emits {property_id, op, value} when the value changes", async () => {
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [{ property_id: 1, op: "eq", value: "" }];
    renderWithProviders(
      <PropertyFilter {...INPUT} definitions={[textDef]} value={existing} onChange={onChange} />
    );
    // Type into the text value input — placeholder "Empty" comes from the
    // text PropertyInput.
    const valueInput = await screen.findByPlaceholderText(/Empty/i);
    await userEvent.type(valueInput, "x");
    expect(onChange).toHaveBeenLastCalledWith([{ property_id: 1, op: "eq", value: "x" }], []);
  });

  it("removes a row, and disables a property another row already uses", async () => {
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [
      { property_id: 1, op: "eq", value: "a" },
      { property_id: 2, op: "eq", value: 1 },
    ];
    renderWithProviders(
      <PropertyFilter
        {...INPUT}
        definitions={[textDef, numberDef]}
        value={existing}
        onChange={onChange}
      />
    );
    const removeButtons = await screen.findAllByRole("button", {
      name: /Remove filter/i,
    });
    expect(removeButtons).toHaveLength(2);
    await userEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith([{ property_id: 2, op: "eq", value: 1 }], []);

    // "Hours" is used in the other row, so the first row's dropdown disables it
    // (and the currently-selected "Owner" stays enabled).
    const propertyCombos = await screen.findAllByLabelText(/Filter by/i);
    await userEvent.click(propertyCombos[0]);
    const hoursOption = await screen.findByRole("option", { name: "Hours" });
    expect(hoursOption).toHaveAttribute("data-disabled");
    const ownerOption = screen.getByRole("option", { name: "Owner" });
    expect(ownerOption).not.toHaveAttribute("data-disabled");
  });

  it("offers a plug-in's fields beside the properties, and emits them apart", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <PropertyFilter
        {...INPUT}
        definitions={[textDef]}
        value={[{ property_id: 1, op: "ilike", value: "ada" }]}
        plugins={{
          fields: [{ id: "plugin:3:ci.issue", name: "Issue", type: MetadataType.number }],
          value: [],
        }}
        onChange={onChange}
      />
    );
    await userEvent.click(await screen.findByRole("button", { name: /Add filter/i }));

    // The next field free is the plug-in's, compared as a number.
    expect(onChange).toHaveBeenCalledWith(
      [{ property_id: 1, op: "ilike", value: "ada" }],
      [{ field: "plugin:3:ci.issue", op: "eq", value: null }]
    );
  });
});

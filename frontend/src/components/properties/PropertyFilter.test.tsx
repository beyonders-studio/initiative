import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition, buildPropertyOption } from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MetadataType, type PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { opsForType, PropertyFilter, type PropertyFilterCondition } from "./PropertyFilter";

const mockDefinitions = (defs: PropertyDefinitionRead[]) => {
  server.use(communityHttp.get("/property-definitions/", () => HttpResponse.json(defs)));
};

describe("opsForType", () => {
  it("returns the expected operators for each property type", () => {
    expect(opsForType(MetadataType.text)).toEqual(["ilike", "eq", "is_null"]);
    expect(opsForType(MetadataType.url)).toEqual(["ilike", "eq", "is_null"]);
    expect(opsForType(MetadataType.number)).toEqual(["eq", "lt", "lte", "gt", "gte", "is_null"]);
    expect(opsForType(MetadataType.date)).toEqual(["eq", "lt", "lte", "gt", "gte", "is_null"]);
    expect(opsForType(MetadataType.datetime)).toEqual(["eq", "lt", "lte", "gt", "gte", "is_null"]);
    expect(opsForType(MetadataType.checkbox)).toEqual(["eq", "is_null"]);
    expect(opsForType(MetadataType.select)).toEqual(["eq", "in_", "is_null"]);
    expect(opsForType(MetadataType.multi_select)).toEqual(["eq"]);
    expect(opsForType(MetadataType.user_reference)).toEqual(["eq", "in_", "is_null"]);
  });
});

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

  it("renders nothing if there are no eligible definitions and no existing filters", async () => {
    mockDefinitions([]);
    const { container } = renderWithProviders(<PropertyFilter value={[]} onChange={vi.fn()} />);
    // Wait one tick for the query to settle.
    await waitFor(() => {
      expect(container.querySelector("button")).toBeNull();
    });
  });

  it("adds a new filter row when the Add button is clicked", async () => {
    mockDefinitions([textDef]);
    const onChange = vi.fn();
    renderWithProviders(<PropertyFilter value={[]} onChange={onChange} />);
    const addBtn = await screen.findByRole("button", { name: /Add property filter/i });
    expect(addBtn).toBeEnabled();
    await userEvent.click(addBtn);
    expect(onChange).toHaveBeenCalledWith([{ property_id: 1, op: "ilike", value: null }], []);
  });

  it("caps the number of filters at the configured max (default 5)", async () => {
    mockDefinitions([
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
    ]);
    const full: PropertyFilterCondition[] = [
      { property_id: 1, op: "eq", value: "a" },
      { property_id: 2, op: "eq", value: 1 },
      { property_id: 3, op: "eq", value: "draft" },
      { property_id: 4, op: "eq", value: "x" },
      { property_id: 5, op: "eq", value: "y" },
    ];
    renderWithProviders(<PropertyFilter value={full} onChange={vi.fn()} />);
    const addBtn = await screen.findByRole("button", { name: /Add property filter/i });
    expect(addBtn).toBeDisabled();
  });

  it("resets op to the first valid op for the new type when the property dropdown changes", async () => {
    mockDefinitions([textDef, numberDef]);
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [{ property_id: 1, op: "ilike", value: "ada" }];
    renderWithProviders(<PropertyFilter value={existing} onChange={onChange} />);
    // The property dropdown is the first combobox in the row.
    const propertyCombo = (await screen.findAllByLabelText(/Property/i))[0];
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
    mockDefinitions([textDef]);
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [{ property_id: 1, op: "eq", value: "" }];
    renderWithProviders(<PropertyFilter value={existing} onChange={onChange} />);
    // Type into the text value input — placeholder "Empty" comes from the
    // text PropertyInput.
    const valueInput = await screen.findByPlaceholderText(/Empty/i);
    await userEvent.type(valueInput, "x");
    expect(onChange).toHaveBeenLastCalledWith([{ property_id: 1, op: "eq", value: "x" }], []);
  });

  it("removes a row when the remove button is clicked", async () => {
    mockDefinitions([textDef, numberDef]);
    const onChange = vi.fn();
    const existing: PropertyFilterCondition[] = [
      { property_id: 1, op: "eq", value: "a" },
      { property_id: 2, op: "eq", value: 1 },
    ];
    renderWithProviders(<PropertyFilter value={existing} onChange={onChange} />);
    const removeButtons = await screen.findAllByRole("button", {
      name: /Remove property filter/i,
    });
    expect(removeButtons).toHaveLength(2);
    await userEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith([{ property_id: 2, op: "eq", value: 1 }], []);
  });

  it("disables already-used property options in the property dropdown", async () => {
    mockDefinitions([textDef, numberDef]);
    const existing: PropertyFilterCondition[] = [
      { property_id: 1, op: "eq", value: "a" },
      { property_id: 2, op: "eq", value: 1 },
    ];
    renderWithProviders(<PropertyFilter value={existing} onChange={vi.fn()} />);
    // Open the first row's property dropdown. "Hours" is used in the other
    // row, so when enumerating options here it must be disabled (and the
    // currently-selected "Owner" must stay enabled).
    const propertyCombos = await screen.findAllByLabelText(/Property/i);
    await userEvent.click(propertyCombos[0]);
    const hoursOption = await screen.findByRole("option", { name: "Hours" });
    expect(hoursOption).toHaveAttribute("data-disabled");
    const ownerOption = screen.getByRole("option", { name: "Owner" });
    expect(ownerOption).not.toHaveAttribute("data-disabled");
  });

  it("offers a plug-in's fields beside the properties, and emits them apart", async () => {
    mockDefinitions([textDef]);
    const onChange = vi.fn();
    renderWithProviders(
      <PropertyFilter
        value={[{ property_id: 1, op: "ilike", value: "ada" }]}
        plugins={{
          fields: [{ id: "plugin:3:ci.issue", name: "Issue", type: MetadataType.number }],
          value: [],
        }}
        onChange={onChange}
      />
    );
    await userEvent.click(await screen.findByRole("button", { name: /Add property filter/i }));

    // The next field free is the plug-in's, compared as a number.
    expect(onChange).toHaveBeenCalledWith(
      [{ property_id: 1, op: "ilike", value: "ada" }],
      [{ field: "plugin:3:ci.issue", op: "eq", value: null }]
    );
  });

  it("gives a multi_select filter a sensible default array value", async () => {
    const multiDef = buildPropertyDefinition({
      id: 10,
      name: "Tags",
      type: MetadataType.multi_select,
      options: [buildPropertyOption({ value: "a", label: "A" })],
    });
    mockDefinitions([multiDef]);
    const onChange = vi.fn();
    renderWithProviders(<PropertyFilter value={[]} onChange={onChange} />);
    const addBtn = await screen.findByRole("button", { name: /Add property filter/i });
    await userEvent.click(addBtn);
    expect(onChange).toHaveBeenCalledWith([{ property_id: 10, op: "eq", value: [] }], []);
  });
});

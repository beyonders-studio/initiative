import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildCollectionFile,
  buildPropertyDefinition,
  buildPropertyOption,
  buildPropertySummary,
} from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { PropertyType } from "@/api/generated/initiativeAPI.schemas";
import { collectionFileFields } from "@/lib/layouts/files";
import type { LayoutNode } from "@/lib/layouts/tree";

import { useCollectionCard } from "./collectionLists";

const moods = ["calm", "grey", "windy"].map((value) =>
  buildPropertyOption({ value, label: value.toUpperCase() })
);
const fields = collectionFileFields(
  [
    buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 }),
    buildPropertyDefinition({
      id: 22,
      name: "Mood",
      type: PropertyType.multi_select,
      options: moods,
      collection_id: 5,
    }),
  ],
  []
);
const harbour = buildCollectionFile({
  name: "Harbour",
  fields: [
    buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk on the water" }),
    buildPropertySummary({
      property_id: 22,
      name: "Mood",
      type: PropertyType.multi_select,
      options: moods,
      value: ["calm", "grey", "windy"],
    }),
  ],
});

const Card = ({ card }: { card: LayoutNode }) => {
  const drawn = useCollectionCard(card, fields);
  return <div data-testid="under">{drawn ? drawn.render(harbour) : "none"}</div>;
};

describe("useCollectionCard", () => {
  it("draws a gallery's card under the picture: the name, then the caption", () => {
    renderWithProviders(
      <Card
        card={{
          type: "card",
          children: [
            { type: "field", props: { field: "name" } },
            { type: "field", props: { field: "property:21" } },
          ],
        }}
      />
    );
    expect(screen.getByText("Harbour")).toBeInTheDocument();
    // The caption itself, as the gallery showed it, not a labelled chip.
    expect(screen.getByText("Dusk on the water")).toBeInTheDocument();
    expect(screen.queryByText(/Caption/)).not.toBeInTheDocument();
  });

  it("draws each field and row on the one line the wall reserves for it", () => {
    renderWithProviders(
      <Card
        card={{
          type: "card",
          children: [
            {
              type: "stack",
              props: { direction: "row", wrap: true },
              children: [
                { type: "field", props: { field: "name" } },
                { type: "field", props: { field: "property:22" } },
              ],
            },
          ],
        }}
      />
    );
    expect(screen.getByText("WINDY")).toBeInTheDocument();
    // Chips past the end are cut off, and the row does not wrap, as the
    // wall's reserved height counts it one line.
    expect(screen.getByTestId("under").querySelector(".flex-wrap")).toBeNull();
  });

  it("draws nothing under a picture whose card shows no fields, as shipped", () => {
    renderWithProviders(<Card card={{ type: "card", children: [] }} />);
    expect(screen.getByTestId("under")).toHaveTextContent("none");
  });
});

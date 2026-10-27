import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildCollectionFile,
  buildPropertyDefinition,
  buildPropertySummary,
} from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { collectionFileFields } from "@/lib/layouts/files";
import type { LayoutNode } from "@/lib/layouts/tree";

import { useCollectionCard } from "./collectionLists";

const fields = collectionFileFields(
  [buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 })],
  []
);
const harbour = buildCollectionFile({
  name: "Harbour",
  fields: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk on the water" })],
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

  it("draws nothing under a picture whose card shows no fields, as shipped", () => {
    renderWithProviders(<Card card={{ type: "card", children: [] }} />);
    expect(screen.getByTestId("under")).toHaveTextContent("none");
  });
});

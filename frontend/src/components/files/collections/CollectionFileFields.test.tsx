import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildCollection,
  buildCollectionFile,
  buildPropertyDefinition,
  buildPropertySummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PropertyValuesSetRequest } from "@/api/generated/initiativeAPI.schemas";

import { CollectionFileFields } from "./CollectionFileFields";

const caption = buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 });

describe("CollectionFileFields", () => {
  it("saves a file's value of the collection's field as the collection's", async () => {
    let sent: { path: string; body: PropertyValuesSetRequest } | null = null;
    server.use(
      communityHttp.put("/collections/:id/files/:fileId/fields", async ({ request, params }) => {
        sent = {
          path: `${String(params.id)}/${String(params.fileId)}`,
          body: (await request.json()) as PropertyValuesSetRequest,
        };
        return HttpResponse.json([
          buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk" }),
        ]);
      })
    );
    const user = userEvent.setup();
    renderWithProviders(
      <CollectionFileFields
        collection={buildCollection({ id: 5, fields: [caption] })}
        file={buildCollectionFile({ id: 4 })}
      />
    );

    await user.type(screen.getByPlaceholderText("Empty"), "Dusk{Enter}");

    await waitFor(() =>
      expect(sent).toEqual({
        path: "5/4",
        body: { values: [{ property_id: 21, value: "Dusk" }], merge: true },
      })
    );
    // The answer stands before the collection is read again.
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Empty")).toHaveValue("Dusk");
  });

  it("shows a reader only the values a file holds", () => {
    renderWithProviders(
      <CollectionFileFields
        collection={buildCollection({
          id: 5,
          fields: [caption, buildPropertyDefinition({ id: 22, name: "Credit", collection_id: 5 })],
          can: { edit: false, unarchive: false },
        })}
        file={buildCollectionFile({
          fields: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk" })],
        })}
      />
    );
    expect(screen.getByText("Dusk")).toBeInTheDocument();
    expect(screen.queryByText("Credit")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

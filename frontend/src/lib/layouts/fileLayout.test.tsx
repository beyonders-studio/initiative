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
import type {
  CollectionFileSummary,
  CollectionRead,
  PropertyValuesSetRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { formatBytes } from "@/lib/fileUtils";

import { DetailLayoutView } from "./DetailLayoutView";
import type { StoredRegions } from "./detailLayout";
import { FILE_DETAIL } from "./fileLayout";

const caption = buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 });

const draw = (
  collection: CollectionRead,
  file: CollectionFileSummary,
  layout: StoredRegions | null = null
) =>
  renderWithProviders(
    <DetailLayoutView detail={FILE_DETAIL} item={file} layout={layout} context={{ collection }} />
  );

describe("a file's detail in a collection", () => {
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
    draw(
      buildCollection({ id: 5, fields: [caption] }),
      buildCollectionFile({ id: 4, name: "Harbour" })
    );

    // As shipped: its name, then every field of the collection's.
    expect(await screen.findByRole("heading", { name: "Harbour" })).toBeInTheDocument();
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

  it("shows a reader only the values a file holds, and its properties as they are", async () => {
    draw(
      buildCollection({
        id: 5,
        fields: [caption, buildPropertyDefinition({ id: 22, name: "Credit", collection_id: 5 })],
        can: { edit: false, unarchive: false },
      }),
      buildCollectionFile({
        fields: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk" })],
        properties: [buildPropertySummary({ property_id: 9, name: "Client", value: "Acme" })],
      })
    );
    expect(await screen.findByText("Dusk")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.queryByText("Credit")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("draws a file's own field and a field of the collection's where its layout puts them", async () => {
    draw(
      buildCollection({ id: 5, fields: [caption] }),
      buildCollectionFile({
        name: "Harbour",
        file_size: 2048,
        fields: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk" })],
        properties: [buildPropertySummary({ property_id: 9, name: "Client", value: "Acme" })],
      }),
      {
        header: [{ type: "field", props: { field: "property:21" } }],
        main: [{ type: "field", props: { field: "size" } }],
        side: [],
      }
    );
    expect(await screen.findByDisplayValue("Dusk")).toBeInTheDocument();
    expect(screen.getByText("Size")).toBeInTheDocument();
    expect(screen.getByText(formatBytes(2048))).toBeInTheDocument();
    // What the layout leaves out is not shown.
    expect(screen.queryByRole("heading", { name: "Harbour" })).not.toBeInTheDocument();
    expect(screen.queryByText("Acme")).not.toBeInTheDocument();
  });
});

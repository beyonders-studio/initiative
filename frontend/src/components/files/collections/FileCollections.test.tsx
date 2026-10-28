import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildCollection,
  buildPropertyDefinition,
  buildPropertySummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { PropertyValuesSetRequest } from "@/api/generated/initiativeAPI.schemas";

import { FileCollections } from "./FileCollections";

describe("FileCollections", () => {
  it("shows and saves the file's values of each collection's properties", async () => {
    let sent: PropertyValuesSetRequest | null = null;
    server.use(
      communityHttp.get("/collections/", () =>
        HttpResponse.json({
          items: [
            buildCollection({
              id: 5,
              name: "Shop",
              metadata: [buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 })],
            }),
            buildCollection({ id: 6, name: "Plain" }),
          ],
        })
      ),
      communityHttp.put("/collections/:id/files/:fileId/metadata", async ({ request }) => {
        sent = (await request.json()) as PropertyValuesSetRequest;
        return HttpResponse.json([]);
      })
    );
    const user = userEvent.setup();
    renderPage(
      () => (
        <FileCollections
          file={{
            id: 4,
            initiative_id: 1,
            collection_ids: [5, 6],
            // The file's read carries each collection's metadata beside its
            // properties.
            properties: [
              buildPropertySummary({
                property_id: 21,
                name: "Caption",
                collection_id: 5,
                value: "Brass lamp",
              }),
            ],
          }}
        />
      ),
      { initialRoute: "/c/1" }
    );

    await screen.findByRole("link", { name: "Plain" });
    // Only a collection with properties of its own has values to show.
    expect(screen.queryByRole("button", { name: "Plain's properties" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Shop's properties" }));
    const caption = await screen.findByDisplayValue("Brass lamp");
    await user.clear(caption);
    await user.type(caption, "Copper lamp{Enter}");

    await waitFor(() =>
      expect(sent).toEqual({ values: [{ property_id: 21, value: "Copper lamp" }], merge: true })
    );
  });
});

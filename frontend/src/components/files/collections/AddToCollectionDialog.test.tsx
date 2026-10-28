import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCollection } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { AddToCollectionDialog } from "@/components/files/collections/AddToCollectionDialog";

const mount = () =>
  renderPage(
    () => <AddToCollectionDialog initiativeId={1} fileIds={[4, 5]} open onOpenChange={() => {}} />,
    { initialRoute: "/c/1" }
  );

describe("AddToCollectionDialog", () => {
  it("offers only the collections the reader may change, and puts the files in one", async () => {
    let added: unknown = null;
    server.use(
      communityHttp.get("/collections/", () =>
        HttpResponse.json({
          items: [
            buildCollection({ id: 2, name: "Store assets" }),
            buildCollection({
              id: 3,
              name: "Someone else's",
              can: { edit: false, unarchive: false },
            }),
          ],
        })
      ),
      communityHttp.post("/collections/:id/files", async ({ params, request }) => {
        added = { id: params.id, ...((await request.json()) as object) };
        return HttpResponse.json(buildCollection({ id: 2 }));
      })
    );
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: "Store assets" }));
    expect(screen.queryByRole("button", { name: "Someone else's" })).not.toBeInTheDocument();
    await waitFor(() => expect(added).toEqual({ id: "2", file_ids: [4, 5] }));
  });

  it("makes a new collection of the files, never an empty one, as the shape picked", async () => {
    let created: unknown = null;
    let shapesRead = 0;
    server.use(
      communityHttp.get("/collections/shapes", () => {
        shapesRead += 1;
        return HttpResponse.json([
          {
            key: "starters",
            name: "Starters",
            entries: [
              {
                key: "catalog",
                name: "Catalog",
                hint: "Things to choose from, priced and rated.",
                lists: ["grid", "table"],
                metadata: [
                  { name: "Price", type: "currency", display: null, currency: "USD" },
                  { name: "Rating", type: "scale", display: "stars", currency: null },
                ],
              },
            ],
          },
        ]);
      }),
      communityHttp.post("/collections/", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json(buildCollection({ id: 9, name: "Round 4" }), { status: 201 });
      })
    );
    const user = userEvent.setup();
    mount();

    const next = await screen.findByRole("button", { name: "Add to new collection" });
    expect(next).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Add to new collection" }), "Round 4");
    await user.click(next);

    // Named, it asks how the collection starts: blank until a shape is picked.
    expect(screen.getByRole("button", { name: /^Blank/ })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("button", { name: /^Catalog/ })).toHaveTextContent(
      "Properties: Price and Rating"
    );
    // The shapes are in the reader's language: another is read afresh.
    await act(() => i18n.changeLanguage("fr"));
    await waitFor(() => expect(shapesRead).toBe(2));
    await act(() => i18n.changeLanguage("en"));
    await user.click(await screen.findByRole("button", { name: /^Catalog/ }));
    await user.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() =>
      expect(created).toEqual({
        initiative_id: 1,
        name: "Round 4",
        file_ids: [4, 5],
        shape: "catalog",
      })
    );
  });

  it("starts a new collection with the shape of another", async () => {
    let created: unknown = null;
    server.use(
      communityHttp.get("/collections/", () =>
        HttpResponse.json({ items: [buildCollection({ id: 2, name: "Store assets" })] })
      ),
      communityHttp.get("/collections/shapes", () => HttpResponse.json([])),
      communityHttp.post("/collections/", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json(buildCollection({ id: 9 }), { status: 201 });
      })
    );
    const user = userEvent.setup();
    mount();

    await user.type(
      await screen.findByRole("textbox", { name: "Add to new collection" }),
      "Round 5"
    );
    await user.click(screen.getByRole("button", { name: "Add to new collection" }));
    await user.click(screen.getByRole("combobox", { name: "Or copy the shape of" }));
    await user.click(await screen.findByRole("option", { name: "Store assets" }));
    await user.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() =>
      expect(created).toEqual({
        initiative_id: 1,
        name: "Round 5",
        file_ids: [4, 5],
        shape_from: 2,
      })
    );
  });
});

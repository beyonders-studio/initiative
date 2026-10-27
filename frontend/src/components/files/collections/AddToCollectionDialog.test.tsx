import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCollection } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
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
            buildCollection({ id: 3, name: "Someone else's", can: { edit: false } }),
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

  it("makes a new collection of the files, never an empty one", async () => {
    let created: unknown = null;
    server.use(
      communityHttp.post("/collections/", async ({ request }) => {
        created = await request.json();
        return HttpResponse.json(buildCollection({ id: 9, name: "Round 4" }), { status: 201 });
      })
    );
    const user = userEvent.setup();
    mount();

    const create = await screen.findByRole("button", { name: "Add to new collection" });
    expect(create).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Add to new collection" }), "Round 4");
    await user.click(create);
    await waitFor(() =>
      expect(created).toEqual({ initiative_id: 1, name: "Round 4", file_ids: [4, 5] })
    );
  });
});

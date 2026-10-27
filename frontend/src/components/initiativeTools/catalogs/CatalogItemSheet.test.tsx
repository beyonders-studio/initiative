import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCatalogItem } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CatalogItemRead } from "@/api/generated/initiativeAPI.schemas";

import { CatalogItemSheet } from "./CatalogItemSheet";

/** Serves `image`, and each change as the server would answer it. */
const serve = (image: CatalogItemRead) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.get("/catalog-items/:itemId", () => HttpResponse.json(image)),
    communityHttp.get("/catalog-items/:itemId/versions", () => HttpResponse.json([])),
    communityHttp.patch("/catalog-items/:itemId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      return HttpResponse.json(Object.assign(image, body));
    })
  );
  return sent;
};

// Drawn on a page: its description holds the page while unsaved.
const open = (image: CatalogItemRead, canEdit = true) =>
  renderPage(() => (
    <CatalogItemSheet
      catalogId={1}
      initiativeId={1}
      image={image}
      open
      onOpenChange={() => {}}
      canEdit={canEdit}
      canDeleteVersions={false}
      isCover={false}
      onSetCover={() => {}}
      onRemoved={() => {}}
    />
  ));

describe("a picture, opened", () => {
  it("is drawn as its catalog lays it out, each field saved on its own", async () => {
    const image = buildCatalogItem({ id: 5, title: "Sketch" });
    const sent = serve(image);
    open(image);
    const user = userEvent.setup();

    const title = await screen.findByDisplayValue("Sketch");
    await user.clear(title);
    await user.type(title, "Final{Enter}");

    await waitFor(() => expect(sent).toEqual([{ title: "Final" }]));
  });

  it("lets its title be cleared, to read as its file's name", async () => {
    const image = buildCatalogItem({ id: 7, title: "Sketch", original_filename: "round-1.png" });
    const sent = serve(image);
    open(image);
    const user = userEvent.setup();

    await user.clear(await screen.findByDisplayValue("Sketch"));
    await user.keyboard("{Enter}");

    await waitFor(() => expect(sent).toEqual([{ title: null }]));
    expect(screen.getByPlaceholderText("round-1.png")).toBeInTheDocument();
  });

  it("shows a reader what it holds, with nothing to change it with", async () => {
    const image = buildCatalogItem({ id: 6, title: "Sketch", description: "Round one" });
    serve(image);
    open(image, false);

    expect(await screen.findByRole("heading", { level: 1, name: "Sketch" })).toBeInTheDocument();
    expect(screen.getByText("Round one")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

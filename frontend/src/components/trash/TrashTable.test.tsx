import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildTrashItem, buildTrashListResponse } from "@/__tests__/factories/trash.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { TrashTable } from "./TrashTable";

// Hoist toast spy so we can assert on it without pulling the whole module.
vi.mock("@/lib/mascotToast", () => {
  const success = vi.fn();
  const error = vi.fn();
  return {
    toast: { success, error },
  };
});

// variant="user" -> cross-community GET /api/v1/me/trash (no community segment).
const myTrashEndpoint = "/api/v1/me/trash";
// variant="community" -> GET /api/v1/c/:communityId/trash/ (community-admin view).
const communityTrashEndpoint = "/trash/";
// restore/purge stay community-scoped, addressed by each item's community_id.
// Each kind's own path: /{kind}/{id}/restore and /{kind}/{id}/purge.
const restoreEndpoint = "/:segment/:id/restore";
const purgeEndpoint = "/:segment/:id/purge";

describe("TrashTable", () => {
  it("renders the empty state when the trash list is empty", async () => {
    server.use(http.get(myTrashEndpoint, () => HttpResponse.json(buildTrashListResponse([]))));

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    expect(await screen.findByText(/Trash is empty\./i)).toBeInTheDocument();
  });

  it("renders one row per trashed item with type badge + name", async () => {
    server.use(
      communityHttp.get(communityTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "project", entity_id: 5, name: "Lost Mines" }),
            buildTrashItem({ entity_type: "task", entity_id: 7, name: "Find the cleric" }),
          ])
        )
      )
    );

    renderWithProviders(<TrashTable variant="community" showPurgeAction />);

    expect(await screen.findByText("Lost Mines")).toBeInTheDocument();
    expect(screen.getByText("Find the cleric")).toBeInTheDocument();
    // entityType labels come from the trash namespace.
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(screen.getByText("Task")).toBeInTheDocument();
  });

  it("pages through the trash, asking the server for each page", async () => {
    const pagesAsked: string[] = [];
    server.use(
      http.get(myTrashEndpoint, ({ request }) => {
        const params = new URL(request.url).searchParams;
        const page = params.get("page");
        pagesAsked.push(`${page}/${params.get("page_size")}`);
        return HttpResponse.json(
          page === "2"
            ? buildTrashListResponse([buildTrashItem({ name: "Older" })], {
                page: 2,
                page_size: 25,
                total_count: 26,
                has_prev: true,
              })
            : buildTrashListResponse([buildTrashItem({ name: "Newest" })], {
                page_size: 25,
                total_count: 26,
                has_next: true,
              })
        );
      })
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Newest");
    await userEvent.click(screen.getByRole("button", { name: /Next/i }));

    expect(await screen.findByText("Older")).toBeInTheDocument();
    expect(pagesAsked).toEqual(["1/25", "2/25"]);
  });

  it("hides the Delete now column when showPurgeAction=false", async () => {
    server.use(
      http.get(myTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([buildTrashItem({ entity_type: "project", name: "Mine" })])
        )
      )
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Mine");
    expect(screen.getByRole("button", { name: /Restore/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete now/i })).not.toBeInTheDocument();
  });

  it("clicking Restore POSTs to the restore endpoint and shows a success toast", async () => {
    const { toast } = await import("@/lib/mascotToast");
    const restoreCalls: string[] = [];

    server.use(
      http.get(myTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "task", entity_id: 42, name: "Test task" }),
          ])
        )
      ),
      communityHttp.post(restoreEndpoint, ({ params }) => {
        restoreCalls.push(`${params.segment}/${params.id}`);
        return HttpResponse.json({ restored: true });
      })
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Test task");
    await userEvent.click(screen.getByRole("button", { name: /Restore/i }));

    await waitFor(() => expect(restoreCalls).toEqual(["tasks/42"]));
    await waitFor(() => expect(toast.success as ReturnType<typeof vi.fn>).toHaveBeenCalled());
  });

  it("clicking Delete now opens a destructive confirmation and purges on confirm", async () => {
    const { toast } = await import("@/lib/mascotToast");
    const purgeCalls: string[] = [];

    server.use(
      communityHttp.get(communityTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "tag", entity_id: 9, name: "old-tag" }),
          ])
        )
      ),
      communityHttp.post(purgeEndpoint, ({ params }) => {
        purgeCalls.push(`${params.segment}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderWithProviders(<TrashTable variant="community" showPurgeAction />);

    await screen.findByText("old-tag");
    await userEvent.click(screen.getByRole("button", { name: /Delete now/i }));

    // ConfirmDialog appears as an alertdialog with a destructive action.
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText(/Delete permanently\?/i)).toBeInTheDocument();

    await userEvent.click(within(confirm).getByRole("button", { name: /Delete forever/i }));

    await waitFor(() => expect(purgeCalls).toEqual(["tags/9"]));
    await waitFor(() => expect(toast.success as ReturnType<typeof vi.fn>).toHaveBeenCalled());
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildTag } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TagRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { toast } from "@/lib/mascotToast";

import { TagBrowser } from "./TagBrowser";

const buildTags = (): TagRead[] => [
  buildTag({ id: 1, name: "Alpha", color: "#ef4444" }),
  buildTag({ id: 2, name: "Beta", color: "#22c55e" }),
  buildTag({ id: 3, name: "Gamma", color: "#3b82f6" }),
];

const renderBrowser = (
  tags = buildTags(),
  props: Partial<React.ComponentProps<typeof TagBrowser>> = {}
) => {
  // TagBrowser rows are TanStack `Link`s, so it needs a real router context.
  const Page = () => <TagBrowser tags={tags} isLoading={false} activeCommunityId={1} {...props} />;
  return renderPage(Page);
};

describe("TagBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a row per tag in normal (navigable) mode", async () => {
    renderBrowser();

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();

    // Normal mode exposes no selection checkboxes or per-row edit affordances.
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit Alpha" })).toBeNull();
  });

  it("select-all checks every row, expands groups, and toggles back off", async () => {
    const onExpandAll = vi.fn();
    const user = userEvent.setup();
    renderBrowser(buildTags(), { editMode: true, onExpandAll });

    await screen.findByText("Alpha");
    // Edit mode reveals selection and per-row edit affordances: 3 row checkboxes
    // + the select-all checkbox in the bulk-action row.
    expect(screen.getAllByRole("checkbox")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Edit Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Beta" })).toBeInTheDocument();
    const selectAll = screen.getByRole("checkbox", { name: "Select all tags" });
    await user.click(selectAll);

    expect(onExpandAll).toHaveBeenCalledTimes(1);
    for (const name of ["Select Alpha", "Select Beta", "Select Gamma"]) {
      expect(screen.getByRole("checkbox", { name })).toBeChecked();
    }
    expect(screen.getByRole("button", { name: "Delete selected (3)" })).toBeEnabled();

    // Toggling again clears the selection (and doesn't re-expand).
    await user.click(selectAll);
    expect(onExpandAll).toHaveBeenCalledTimes(1);
    for (const name of ["Select Alpha", "Select Beta", "Select Gamma"]) {
      expect(screen.getByRole("checkbox", { name })).not.toBeChecked();
    }
    expect(screen.getByRole("button", { name: "Delete selected (0)" })).toBeDisabled();
  });

  it("renames a tag through the edit dialog (PATCH)", async () => {
    let patchBody: { name?: string; color?: string } | null = null;
    server.use(
      communityHttp.patch("/tags/:tagId", async ({ request, params }) => {
        patchBody = (await request.json()) as { name?: string; color?: string };
        return HttpResponse.json({
          id: Number(params.tagId),
          name: patchBody.name,
          color: patchBody.color,
          community_id: 1,
          created_at: "2026-01-15T00:00:00.000Z",
          updated_at: "2026-01-15T00:00:00.000Z",
        });
      })
    );

    const user = userEvent.setup();
    renderBrowser(buildTags(), { editMode: true });

    await user.click(await screen.findByRole("button", { name: "Edit Alpha" }));

    const input = await screen.findByRole("textbox");
    expect(input).toHaveValue("Alpha");
    await user.clear(input);
    await user.type(input, "Alpha renamed");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(patchBody).toEqual({ name: "Alpha renamed", color: "#ef4444" }));
  });

  it("bulk-deletes every selected tag (DELETE per id) with one summary toast", async () => {
    const deletedIds: number[] = [];
    server.use(
      communityHttp.delete("/tags/:tagId", ({ params }) => {
        deletedIds.push(Number(params.tagId));
        return new HttpResponse(null, { status: 204 });
      })
    );

    const user = userEvent.setup();
    renderBrowser(buildTags(), { editMode: true });

    await user.click(await screen.findByRole("checkbox", { name: "Select Alpha" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Beta" }));

    await user.click(screen.getByRole("button", { name: "Delete selected (2)" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deletedIds).toHaveLength(2));
    expect([...deletedIds].sort()).toEqual([1, 2]);
    // Gamma was never selected, so it is untouched.
    expect(deletedIds).not.toContain(3);
    expect(toast.success).toHaveBeenCalledWith("2 tags deleted.");
  });
});

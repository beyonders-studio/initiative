/**
 * The template picker on the new-file dialog.
 *
 * It is backed by the community lookup, which matches words — and before anything
 * is typed there are none, so the picker opened on "No templates available" in
 * a community with plenty of them. What it opens on now is the recent list,
 * asked for blueprints, which is the only way it can say that templates exist
 * at all.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildSearchSuggestion } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { CreateFileDialog } from "./CreateFileDialog";

const page = () => () => <CreateFileDialog open onOpenChange={() => {}} initiativeId={7} />;

describe("CreateFileDialog", () => {
  it("offers templates before anything is typed", async () => {
    const asked: URL[] = [];
    server.use(
      communityHttp.get("/search/recent", ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json([
          buildSearchSuggestion({
            entity_type: "file",
            tool: Tool.file,
            title: "Session prep",
            initiative_id: 7,
          }),
        ]);
      })
    );

    renderPage(page());

    await userEvent.click(await screen.findByRole("combobox", { name: /start from template/i }));
    expect(await screen.findByText("Session prep")).toBeInTheDocument();

    // Narrowed the same way typing would narrow it, so the list it opens on
    // can hold nothing its own search would refuse to find.
    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    expect(asked[0].searchParams.get("is_template")).toBe("true");
    expect(asked[0].searchParams.getAll("types")).toEqual(["file"]);
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildPost,
  buildPropertyDefinition,
  buildTag,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { definitionsHandler } from "@/__tests__/helpers/handlers/property.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { CreatePostDialog } from "./CreatePostDialog";

vi.mock("@/components/ui/editor/editor", () => ({ Editor: () => null }));

const required = (field: string) => ({ type: "field", props: { field, required: true } });

describe("CreatePostDialog", () => {
  it("asks for what the posts page requires, and posts nothing until it has it", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "post",
                task_type_id: null,
                task_type_name: null,
                definition: { main: [required("tags"), required("property:12")] },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      ),
      definitionsHandler([buildPropertyDefinition({ id: 12, name: "Audience", type: "text" })]),
      communityHttp.get("/tags/", () => HttpResponse.json([buildTag({ id: 7, name: "News" })])),
      communityHttp.post("/posts/", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(buildPost({ id: 3 }), { status: 201 });
      })
    );
    renderPage(() => <CreatePostDialog open onOpenChange={() => {}} initiativeId={1} />);
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Headline"), "Market day");
    const post = screen.getByRole("button", { name: "New Post" });
    const audience = await screen.findByRole("group", { name: "Audience" });
    expect(post).toBeDisabled();
    expect(screen.getByText("Fill in what is required to add it.")).toBeInTheDocument();

    await user.click(within(screen.getByRole("group", { name: "Tags" })).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "News" }));
    expect(post).toBeDisabled();
    await user.type(within(audience).getByRole("textbox"), "Everyone");
    await waitFor(() => expect(post).toBeEnabled());
    await user.click(post);

    await waitFor(() =>
      expect(sent).toEqual(
        expect.objectContaining({
          name: "Market day",
          tag_ids: [7],
          properties: [{ property_id: 12, value: "Everyone" }],
        })
      )
    );
  });
});

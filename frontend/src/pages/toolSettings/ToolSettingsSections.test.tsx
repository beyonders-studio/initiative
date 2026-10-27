import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildPost,
  buildPropertySummary,
  buildShareRequest,
  buildTagSummary,
  initiativeCan,
  ownerCan,
  readerCan,
  resetFactories,
  writerCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { PostReactionsField } from "@/components/initiativeTools/posts/PostReactionsField";
import {
  type ToolMutation,
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "@/components/tools/settings/ToolSettingsContext";

import { ToolSettingsAccessPage } from "./ToolSettingsAccessPage";
import { ToolSettingsAdvancedPage } from "./ToolSettingsAdvancedPage";
import { ToolSettingsDetailsPage } from "./ToolSettingsDetailsPage";

const ADDED_TAG = buildTagSummary({ id: 99, name: "Added tag" });

// The picker's own UI is not what these tests are about — this stub reports the
// selection it was handed and offers one way to change it.
vi.mock("@/components/tags", () => ({
  TagPicker: ({
    selectedTags,
    onChange,
  }: {
    selectedTags: { id: number; name: string }[];
    onChange: (tags: { id: number; name: string }[]) => void;
  }) => (
    <div>
      <span data-testid="selected-tags">{selectedTags.map((tag) => tag.name).join(",")}</span>
      <button type="button" onClick={() => onChange([ADDED_TAG])}>
        pick tag
      </button>
    </div>
  ),
}));

const buildEntity = (overrides: Partial<ToolSettingsEntity> = {}): ToolSettingsEntity => ({
  id: 7,
  name: "Q3 Roadmap",
  description: "A description",
  initiative_id: 3,
  can: ownerCan(),
  tags: [],
  grants: [],
  comments_enabled: true,
  archived_at: null,
  ...overrides,
});

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

/** One section, mounted the way its route mounts it: inside the frame's context. */
const renderSection = (
  Section: React.ComponentType,
  entity: ToolSettingsEntity,
  tool: Tool = Tool.queue,
  template?: ToolMutation<{ is_template: boolean }>
) =>
  renderPage(() => (
    <ToolSettingsProvider
      value={{
        tool,
        entity,
        template,
        setGrants: noopMutation(),
        remove: noopMutation(),
      }}
    >
      <Section />
    </ToolSettingsProvider>
  ));

describe("ToolSettingsDetailsPage tags", () => {
  it("keeps the new selection when the write succeeds", async () => {
    resetFactories();
    server.use(
      communityHttp.put("/tools/:tool/:toolId/tags", () => HttpResponse.json([ADDED_TAG]))
    );
    renderSection(ToolSettingsDetailsPage, buildEntity());

    await userEvent.click(await screen.findByRole("button", { name: "pick tag" }));

    await waitFor(() => expect(screen.getByTestId("selected-tags")).toHaveTextContent("Added tag"));
  });

  it("puts the previous selection back when the write fails", async () => {
    resetFactories();
    const existing = buildTagSummary({ id: 1, name: "Existing tag" });
    server.use(
      communityHttp.put("/tools/:tool/:toolId/tags", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity({ tags: [existing] }));

    expect(await screen.findByTestId("selected-tags")).toHaveTextContent("Existing tag");

    await userEvent.click(screen.getByRole("button", { name: "pick tag" }));

    // Shown optimistically, then rolled back — the picker must never keep a
    // selection the server rejected.
    await waitFor(() =>
      expect(screen.getByTestId("selected-tags")).toHaveTextContent("Existing tag")
    );
    expect(screen.getByTestId("selected-tags")).not.toHaveTextContent("Added tag");
  });
});

describe("ToolSettingsDetailsPage properties", () => {
  it("shows what a tool in an initiative carries", async () => {
    resetFactories();
    renderSection(
      ToolSettingsDetailsPage,
      buildEntity({ properties: [buildPropertySummary({ name: "Budget" })] })
    );

    expect(await screen.findByText("Budget")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Properties" })).toBeInTheDocument();
  });

  it("offers none on a community-level tool, which has no definitions to add", async () => {
    resetFactories();
    renderSection(ToolSettingsDetailsPage, buildEntity({ initiative_id: null }));

    await screen.findByRole("switch", { name: "Enable comments" });
    expect(screen.queryByText("Properties")).not.toBeInTheDocument();
  });
});

describe("ToolSettingsDetailsPage comments switch", () => {
  it("turns comments off and keeps the new state", async () => {
    resetFactories();
    server.use(
      communityHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ comments_enabled: false })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity());

    // Stated the way it is labelled: on means comments happen.
    const toggle = await screen.findByRole("switch", { name: "Enable comments" });
    expect(toggle).toBeChecked();

    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).not.toBeChecked());
  });

  it("puts the switch back when the write fails", async () => {
    resetFactories();
    server.use(
      communityHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity());

    const toggle = await screen.findByRole("switch", { name: "Enable comments" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });
});

describe("PostReactionsField", () => {
  const servePost = (reactions_enabled: boolean) =>
    communityHttp.get("/posts/:postId", () =>
      HttpResponse.json(buildPost({ id: 7, reactions_enabled }))
    );

  it("starts from the post and keeps the new state", async () => {
    resetFactories();
    server.use(
      servePost(false),
      communityHttp.put("/posts/:postId/reactions", () =>
        HttpResponse.json({ reactions_enabled: true })
      )
    );
    renderSection(PostReactionsField, buildEntity(), Tool.post);

    const toggle = await screen.findByRole("switch", { name: "Reactions" });
    await waitFor(() => expect(toggle).not.toBeChecked());

    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("puts the switch back when the write fails", async () => {
    resetFactories();
    server.use(
      servePost(true),
      communityHttp.put("/posts/:postId/reactions", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSection(PostReactionsField, buildEntity(), Tool.post);

    const toggle = await screen.findByRole("switch", { name: "Reactions" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("is read-only to someone who may not edit the post", async () => {
    resetFactories();
    server.use(servePost(true));
    renderSection(PostReactionsField, buildEntity({ can: readerCan() }), Tool.post);

    expect(await screen.findByRole("switch", { name: "Reactions" })).toBeDisabled();
  });
});

describe("ToolSettingsDetailsPage template switch", () => {
  it("marks it a template", async () => {
    const template = noopMutation();
    renderSection(
      ToolSettingsDetailsPage,
      buildEntity({ is_template: false }),
      Tool.project,
      template
    );

    const toggle = await screen.findByRole("switch", { name: "Toggle template status" });
    await userEvent.click(toggle);

    expect(template.mutate).toHaveBeenCalledWith({ is_template: true }, expect.anything());
    expect(toggle).toBeChecked();
  });

  it("puts the switch back when the write fails", async () => {
    const template = {
      mutate: vi.fn((_vars, options?: { onError?: () => void }) => options?.onError?.()),
      isPending: false,
    };
    renderSection(
      ToolSettingsDetailsPage,
      buildEntity({ is_template: true }),
      Tool.project,
      template
    );

    const toggle = await screen.findByRole("switch", { name: "Toggle template status" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("is not offered for a tool without templates", async () => {
    renderSection(ToolSettingsDetailsPage, buildEntity());

    await screen.findByRole("switch", { name: "Enable comments" });
    expect(screen.queryByRole("switch", { name: "Toggle template status" })).toBeNull();
  });
});

describe("ToolSettingsAdvancedPage", () => {
  it("offers deletion to the owner", async () => {
    resetFactories();
    renderSection(ToolSettingsAdvancedPage, buildEntity());

    expect(await screen.findByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("says so rather than rendering a blank page when it holds nothing", async () => {
    resetFactories();
    // Deletion is the owner's alone and this tool declares no extras, so the
    // tab bar hides the link — but the address is still typeable.
    renderSection(ToolSettingsAdvancedPage, buildEntity({ can: readerCan() }));

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("offers the way back out of the archive, which nothing else on it offers", async () => {
    resetFactories();
    // What an archived entity arrives as: nothing on it may be changed but
    // taking it back out.
    renderSection(
      ToolSettingsAdvancedPage,
      buildEntity({
        can: readerCan({ unarchive: true }),
        archived_at: "2026-09-01T00:00:00Z",
      })
    );

    expect(await screen.findByRole("button", { name: "Unarchive" })).toBeInTheDocument();
  });

  it("offers no way back to someone who could not write it anyway", async () => {
    resetFactories();
    renderSection(
      ToolSettingsAdvancedPage,
      buildEntity({
        can: readerCan(),
        archived_at: "2026-09-01T00:00:00Z",
      })
    );

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unarchive" })).not.toBeInTheDocument();
  });

  it("offers archiving on a live tool to someone who may write it", async () => {
    resetFactories();
    renderSection(ToolSettingsAdvancedPage, buildEntity({ can: writerCan() }));

    expect(await screen.findByRole("button", { name: "Archive" })).toBeInTheDocument();
  });
  it("offers the owner an export of the tool", async () => {
    resetFactories();
    let sent: { format: string | null; ids: string | null } | null = null;
    server.use(
      communityHttp.get("/exports/queue", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          ids: url.searchParams.get("ids"),
        };
        return new HttpResponse("a,b", { status: 200, headers: { "Content-Type": "text/csv" } });
      })
    );
    renderSection(ToolSettingsAdvancedPage, buildEntity());

    expect(await screen.findByText("Download a copy", { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    await userEvent.click(await screen.findByRole("button", { name: "CSV" }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).toEqual({ format: "csv", ids: "7" }));
  });

  it("copies it into the initiative chosen, the suggested name following the choice", async () => {
    resetFactories();
    const can = initiativeCan({ create: [Tool.counter_group] });
    let sent: unknown = null;
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: 3, name: "Here", can }),
          buildInitiative({ id: 4, name: "There", can }),
        ])
      ),
      communityHttp.post("/counter-groups/:groupId/duplicate", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ id: 8, initiative_id: 4 }, { status: 201 });
      })
    );
    renderSection(ToolSettingsAdvancedPage, buildEntity(), Tool.counter_group);

    await userEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Q3 Roadmap (Copy)");
    await userEvent.click(within(dialog).getByLabelText("Initiative"));
    await userEvent.click(await screen.findByRole("option", { name: "There" }));
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Q3 Roadmap");
    await userEvent.click(within(dialog).getByRole("button", { name: "Duplicate" }));

    await waitFor(() => expect(sent).toEqual({ name: "Q3 Roadmap", target_initiative_id: 4 }));
  });

  it("copies an initiative that keeps its content in only beside itself", async () => {
    resetFactories();
    const can = initiativeCan({ create: [Tool.counter_group] });
    const here = buildInitiative({ id: 3, name: "Here", can, keep_content_in: true });
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([here, buildInitiative({ id: 4, name: "There", can })])
      ),
      communityHttp.get("/initiatives/:id", () => HttpResponse.json(here))
    );
    renderSection(ToolSettingsAdvancedPage, buildEntity(), Tool.counter_group);

    await userEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText("Initiative"));
    expect(await screen.findByRole("option", { name: "Here" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "There" })).not.toBeInTheDocument();
  });

  it("offers no copy of a post, which is published rather than reused", async () => {
    resetFactories();
    renderSection(ToolSettingsAdvancedPage, buildEntity(), Tool.post);

    expect(await screen.findByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Duplicate" })).not.toBeInTheDocument();
  });

  it("offers no export to someone who may edit it but not delete it", async () => {
    resetFactories();
    renderSection(ToolSettingsAdvancedPage, buildEntity({ can: writerCan() }));

    expect(await screen.findByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
  });
});

describe("ToolSettingsAccessPage", () => {
  it("refuses a reader who reached the address without write access", async () => {
    resetFactories();
    // The tab bar hides this section from them; the address is still typeable,
    // so the section says no on its own.
    renderSection(ToolSettingsAccessPage, buildEntity({ can: readerCan() }));

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
  });

  it.each([
    ["shares at the level asked for", "Share", { approve: true, level: "write", tell: false }],
    [
      "declines, telling them when asked to",
      "Decline",
      { approve: false, level: null, tell: true },
    ],
  ])("answers a request: %s", async (_, button, expected) => {
    resetFactories();
    const request = buildShareRequest({ level: "write", message: "For the launch" });
    let body: unknown = null;
    server.use(
      communityHttp.get("/share-requests/", () => HttpResponse.json([request])),
      communityHttp.post("/share-requests/answer", async ({ request: sent }) => {
        body = await sent.json();
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderSection(ToolSettingsAccessPage, buildEntity());

    expect(await screen.findByText("For the launch")).toBeInTheDocument();
    if (expected.tell) await userEvent.click(screen.getByRole("checkbox", { name: "Tell them" }));
    await userEvent.click(screen.getByRole("button", { name: button }));

    await waitFor(() => expect(body).toEqual({ ids: [request.id], scope: "user", ...expected }));
  });
});

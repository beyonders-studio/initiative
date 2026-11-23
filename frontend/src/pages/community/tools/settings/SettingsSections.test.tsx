import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
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
import { PostReactionsField } from "@/pages/community/tools/posts/PostReactionsField";

import { AccessPage } from "./AccessPage";
import { AdvancedPage } from "./AdvancedPage";
import { DetailsPage } from "./DetailsPage";
import {
  type ToolMutation,
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "./ToolSettingsContext";

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
  tool: Tool = Tool.contact,
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

describe("DetailsPage tags", () => {
  it("keeps the new selection when the write succeeds", async () => {
    resetFactories();
    server.use(
      communityHttp.put("/tools/:tool/:toolId/tags", () => HttpResponse.json([ADDED_TAG]))
    );
    renderSection(DetailsPage, buildEntity());

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
    renderSection(DetailsPage, buildEntity({ tags: [existing] }));

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

// These settings fill themselves in from the entity the frame loaded. A fresh
// copy arrives for reasons that have nothing to do with the reader (a realtime
// signal, a window brought back to the front, another query's mutation), and
// handing the section a changed entity is exactly what those refetches do.
describe("DetailsPage during a background refetch", () => {
  /** The section as its route mounts it, a button standing in for the moment a
   *  fresh copy of the entity arrives. */
  const renderRefetching = () => {
    const Harness = () => {
      const [entity, setEntity] = useState(buildEntity());
      return (
        <>
          <button
            type="button"
            onClick={() => setEntity(buildEntity({ name: "Renamed by somebody else" }))}
          >
            refetch
          </button>
          <ToolSettingsProvider
            value={{
              tool: Tool.wiki,
              entity,
              update: noopMutation(),
              setGrants: noopMutation(),
              remove: noopMutation(),
            }}
          >
            <DetailsPage />
          </ToolSettingsProvider>
        </>
      );
    };
    return renderPage(Harness);
  };

  it("keeps what has been typed when a fresh copy of the entity arrives", async () => {
    renderRefetching();
    const user = userEvent.setup();

    await user.clear(await screen.findByLabelText(/name/i));
    await user.type(screen.getByLabelText(/name/i), "Half-written name");
    await user.click(screen.getByRole("button", { name: "refetch" }));

    await waitFor(() => expect(screen.getByLabelText(/name/i)).toHaveValue("Half-written name"));
  });

  it("catches up with a rename while nobody is typing", async () => {
    renderRefetching();
    expect(await screen.findByLabelText(/name/i)).toHaveValue("Q3 Roadmap");

    await userEvent.click(screen.getByRole("button", { name: "refetch" }));

    await waitFor(() =>
      expect(screen.getByLabelText(/name/i)).toHaveValue("Renamed by somebody else")
    );
  });
});

describe("DetailsPage properties", () => {
  it("shows what a tool in an initiative carries", async () => {
    resetFactories();
    renderSection(
      DetailsPage,
      buildEntity({ properties: [buildPropertySummary({ name: "Budget" })] })
    );

    expect(await screen.findByText("Budget")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Metadata" })).toBeInTheDocument();
  });

  it("offers none on a community-level tool, which has no definitions to add", async () => {
    resetFactories();
    renderSection(DetailsPage, buildEntity({ initiative_id: null }));

    await screen.findByRole("switch", { name: "Enable comments" });
    expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
  });
});

describe("DetailsPage comments switch", () => {
  it("turns comments off and keeps the new state", async () => {
    resetFactories();
    server.use(
      communityHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ comments_enabled: false })
      )
    );
    renderSection(DetailsPage, buildEntity());

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
    renderSection(DetailsPage, buildEntity());

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

describe("DetailsPage template switch", () => {
  it("marks it a template", async () => {
    const template = noopMutation();
    renderSection(DetailsPage, buildEntity({ is_template: false }), Tool.project, template);

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
    renderSection(DetailsPage, buildEntity({ is_template: true }), Tool.project, template);

    const toggle = await screen.findByRole("switch", { name: "Toggle template status" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("is not offered for a tool without templates", async () => {
    renderSection(DetailsPage, buildEntity());

    await screen.findByRole("switch", { name: "Enable comments" });
    expect(screen.queryByRole("switch", { name: "Toggle template status" })).toBeNull();
  });
});

describe("AdvancedPage", () => {
  // Deletion is the owner's alone and this tool declares no extras, so the tab
  // bar hides the link — but the address is still typeable, live or archived.
  it.each([null, "2026-09-01T00:00:00Z"])(
    "says so rather than rendering a blank page when it holds nothing for a reader (archived: %s)",
    async (archived_at) => {
      resetFactories();
      renderSection(AdvancedPage, buildEntity({ can: readerCan(), archived_at }));

      expect(await screen.findByText("Permission required")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Unarchive" })).not.toBeInTheDocument();
    }
  );

  it("offers the way back out of the archive, which nothing else on it offers", async () => {
    resetFactories();
    // What an archived entity arrives as: nothing on it may be changed but
    // taking it back out.
    renderSection(
      AdvancedPage,
      buildEntity({
        can: readerCan({ unarchive: true }),
        archived_at: "2026-09-01T00:00:00Z",
      })
    );

    expect(await screen.findByRole("button", { name: "Unarchive" })).toBeInTheDocument();
  });

  it("offers archiving but no export on a live tool to someone who may write it", async () => {
    resetFactories();
    renderSection(AdvancedPage, buildEntity({ can: writerCan() }));

    expect(await screen.findByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
  });
  it("offers the owner an export of the tool", async () => {
    resetFactories();
    let sent: { format: string | null; ids: string | null } | null = null;
    server.use(
      communityHttp.get("/exports/contact", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          ids: url.searchParams.get("ids"),
        };
        return new HttpResponse("a,b", { status: 200, headers: { "Content-Type": "text/csv" } });
      })
    );
    renderSection(AdvancedPage, buildEntity());

    expect(await screen.findByText("Download a copy", { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    await userEvent.click(await screen.findByRole("button", { name: "CSV" }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).toEqual({ format: "csv", ids: "7" }));
  });

  it.each([
    // One format: nothing to choose, so the wizard opens on it.
    [Tool.dashboard, ["Importable file (.json)"]],
    // A wiki's every download is a zip.
    [Tool.wiki, ["PDF (.zip)", "Markdown (.zip)", "Word (.zip)", "Importable file (.zip)"]],
  ])("offers the owner of a %s its own export formats", async (tool, formats) => {
    resetFactories();
    renderSection(AdvancedPage, buildEntity(), tool);

    await userEvent.click(await screen.findByRole("button", { name: "Export" }));

    for (const name of formats) expect(await screen.findByText(name)).toBeInTheDocument();
    if (formats.length === 1) {
      expect(screen.getByRole("button", { name: /start export/i })).toBeInTheDocument();
    }
  });

  it("copies it into the initiative chosen, the suggested name following the choice", async () => {
    resetFactories();
    const can = initiativeCan({ create: [Tool.contact] });
    let sent: unknown = null;
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: 3, name: "Here", can }),
          buildInitiative({ id: 4, name: "There", can }),
        ])
      ),
      communityHttp.post("/contacts/:contactId/duplicate", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ id: 8, initiative_id: 4 }, { status: 201 });
      })
    );
    renderSection(AdvancedPage, buildEntity(), Tool.contact);

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
    const can = initiativeCan({ create: [Tool.contact] });
    const here = buildInitiative({ id: 3, name: "Here", can, keep_content_in: true });
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([here, buildInitiative({ id: 4, name: "There", can })])
      ),
      communityHttp.get("/initiatives/:id", () => HttpResponse.json(here))
    );
    renderSection(AdvancedPage, buildEntity(), Tool.contact);

    await userEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText("Initiative"));
    expect(await screen.findByRole("option", { name: "Here" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "There" })).not.toBeInTheDocument();
  });

  it("offers its owner deletion, but no copy of a post, which is published rather than reused", async () => {
    resetFactories();
    renderSection(AdvancedPage, buildEntity(), Tool.post);

    expect(await screen.findByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Duplicate" })).not.toBeInTheDocument();
  });
});

describe("AccessPage", () => {
  it("refuses a reader who reached the address without write access", async () => {
    resetFactories();
    // The tab bar hides this section from them; the address is still typeable,
    // so the section says no on its own.
    renderSection(AccessPage, buildEntity({ can: readerCan() }));

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
    renderSection(AccessPage, buildEntity());

    expect(await screen.findByText("For the launch")).toBeInTheDocument();
    if (expected.tell) await userEvent.click(screen.getByRole("checkbox", { name: "Tell them" }));
    await userEvent.click(screen.getByRole("button", { name: button }));

    await waitFor(() => expect(body).toEqual({ ids: [request.id], scope: "user", ...expected }));
  });
});

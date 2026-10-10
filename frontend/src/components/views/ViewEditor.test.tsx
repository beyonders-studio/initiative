/**
 * The view editor, worked as a manager works it: change the open view in the
 * outline or on the canvas, see it at once, and nothing is stored until Save.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildTask,
  buildTaskListResponse,
  buildToolView,
  buildToolViewSet,
} from "@/__tests__/factories";
import { buildSavedViewSet } from "@/__tests__/factories/toolView.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { ToolViewSetRead, ToolViewSetWrite } from "@/api/generated/initiativeAPI.schemas";
import { useProjectViews } from "@/hooks/useProjectViews";
import type { ViewNode } from "@/lib/views/tree";

import { TASK_PAGE, ViewEditor } from "./ViewEditor";

const STATUSES = buildDefaultTaskStatuses(1);

let saves: ToolViewSetWrite[] = [];

/** The editor as its page holds it: on the project's views as read, which a
 *  save writes its answer over. */
const editor = (slug: string, onClose = vi.fn(), set = buildToolViewSet()) => {
  server.use(communityHttp.get("/views/", () => HttpResponse.json(set)));
  const Page = () => {
    const read = useProjectViews(1).data;
    return read ? (
      <ViewEditor
        projectId={1}
        initiativeId={1}
        statuses={STATUSES}
        set={read}
        initialSlug={slug}
        onClose={onClose}
      />
    ) : null;
  };
  renderPage(Page);
  return { user: userEvent.setup(), onClose };
};

const outline = () => screen.findByRole("navigation", { name: /outline/i });
const canvas = () => screen.findByRole("region", { name: /preview/i });

beforeEach(() => {
  saves = [];
  server.use(
    communityHttp.get("/tasks/:taskId", () =>
      HttpResponse.json({
        ...buildTask({
          id: 7,
          project_id: 1,
          title: "Draw the map",
          task_status_id: STATUSES[0].id,
        }),
        description: "Every road, to scale.",
      })
    ),
    communityHttp.get("/tasks/", () =>
      HttpResponse.json(
        buildTaskListResponse([
          buildTask({
            id: 7,
            project_id: 1,
            title: "Draw the map",
            priority: "medium",
            task_status_id: STATUSES[0].id,
          }),
        ])
      )
    ),
    communityHttp.get("/property-definitions/", () =>
      HttpResponse.json([buildPropertyDefinition({ id: 12, name: "Effort" })])
    ),
    communityHttp.put("/views/", async ({ request }) => {
      const body = (await request.json()) as ToolViewSetWrite;
      saves.push(body);
      return HttpResponse.json(buildSavedViewSet(body));
    })
  );
});

describe("ViewEditor", () => {
  it("takes a field off the card at once, and stores it only on Save", async () => {
    const { user } = editor("board");
    expect(await within(await canvas()).findByText(/priority: medium/i)).toBeInTheDocument();

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));

    expect(within(await canvas()).queryByText(/priority: medium/i)).not.toBeInTheDocument();
    expect(saves).toEqual([]);
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(saves).toHaveLength(1));
    const board = saves[0].views.find((view) => view.slug === "board");
    expect(JSON.stringify(board?.definition.card)).not.toContain('"priority"');
  });

  it("puts back what was undone", async () => {
    const { user } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /^undo$/i }));

    expect(within(await canvas()).getByText(/priority: medium/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("selects the part clicked on the canvas, in the outline", async () => {
    const { user } = editor("board");

    await user.click(await within(await canvas()).findByText(/priority: medium/i));

    expect(within(await outline()).getByRole("button", { name: "Priority" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("adds a property to a table as a column, named by its id", async () => {
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    await user.click(await screen.findByRole("button", { name: "Effort" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0].views.find((view) => view.slug === "table")?.definition.columns).toEqual([
      "title",
      "startDate",
      "dueDate",
      "priority",
      "tags",
      "comments",
      "property:12",
    ]);
  });

  it("changes nothing while a save is under way, and still asks before leaving", async () => {
    let answer = () => {};
    server.use(
      communityHttp.put("/views/", async ({ request }) => {
        const body = (await request.json()) as ToolViewSetWrite;
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return HttpResponse.json(buildSavedViewSet(body));
      })
    );
    const { user, onClose } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByRole("button", { name: /saving/i })).toBeDisabled();
    expect(within(await outline()).getByRole("button", { name: /hide tags/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^undo$/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(await screen.findByText(/still being saved/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /keep editing/i }));

    answer();
    expect(await screen.findByRole("button", { name: /^save$/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("adds a plug-in's field to a table as a column", async () => {
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({
          items: [
            {
              id: 3,
              name: "CI",
              enabled: true,
              definition: {
                fields: [{ key: "ci.state", name: { en: "Build" }, kind: "badge", on: ["task"] }],
              },
              item_initiatives: [1],
              item_fields: ["ci.state"],
              item_parts: [],
              item_actions: [],
            },
          ],
        })
      )
    );
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    expect(await screen.findByText("CI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Build" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0].views.find((view) => view.slug === "table")?.definition.columns?.at(-1)).toBe(
      "plugin:3:ci.state"
    );
  });

  it("opens the default view when another save takes away the open one", async () => {
    const shipped = buildToolViewSet();
    const refreshed = buildSavedViewSet({
      views: shipped.views.filter((view) => !["unassigned", "mine"].includes(view.slug)),
      item_layouts: [],
    });
    const Refreshing = () => {
      const [set, setSet] = useState<ToolViewSetRead>(shipped);
      return (
        <>
          <button type="button" onClick={() => setSet(refreshed)}>
            refresh
          </button>
          <ViewEditor
            projectId={1}
            initiativeId={1}
            statuses={STATUSES}
            set={set}
            initialSlug="mine"
            onClose={vi.fn()}
          />
        </>
      );
    };
    renderPage(Refreshing);
    const user = userEvent.setup();
    expect(await screen.findByRole("combobox", { name: /^view being edited$/i })).toHaveTextContent(
      "Mine"
    );

    await user.click(screen.getByRole("button", { name: "refresh" }));
    expect(screen.getByRole("combobox", { name: /^view being edited$/i })).toHaveTextContent(
      "Table"
    );
    const name = screen.getByLabelText(/^name$/i);
    await user.clear(name);
    await user.type(name, "Everything{Enter}");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0].views.map((view) => [view.slug, view.name, view.is_default])).toEqual([
      ["table", "Everything", true],
      ["board", "Board", false],
      ["calendar", "Calendar", false],
      ["incomplete", "Incomplete", false],
    ]);
  });

  it("asks before leaving with changes, and leaves at once without", async () => {
    const { user, onClose } = editor("board");
    await within(await canvas()).findByText(/priority: medium/i);

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));
    await user.click(screen.getByRole("button", { name: /close the editor/i }));
    expect(await screen.findByText(/leave without saving/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /^leave$/i }));

    expect(onClose).toHaveBeenCalled();
  });

  describe("on the canvas", () => {
    it("adds a part before the one pointed at", async () => {
      const { user } = editor("board");
      await user.hover(await within(await canvas()).findByText(/priority: medium/i));

      // Clicked where it is, as the pointer reaches it from the part.
      fireEvent.click(screen.getByRole("button", { name: /add before priority/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: "Group" }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      const card = saves[0].views.find((view) => view.slug === "board")?.definition.card;
      // The row holding Priority starts with the group, Priority after it.
      expect((card?.children?.[1] as ViewNode | undefined)?.children?.slice(0, 2)).toEqual([
        { type: "stack", props: { align: "start" }, children: [] },
        { type: "field", props: { field: "priority" } },
      ]);
    });

    it("adds a column after the one pointed at", async () => {
      const { user } = editor("table");
      const header = await within(await canvas()).findByRole("columnheader", { name: /priority/i });
      await user.hover(within(header).getByText(/priority/i));

      fireEvent.click(screen.getByRole("button", { name: /add after priority/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: "Effort" }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(saves[0].views.find((view) => view.slug === "table")?.definition.columns).toEqual([
        "title",
        "startDate",
        "dueDate",
        "priority",
        "property:12",
        "tags",
        "comments",
      ]);
    });

    it("moves the selected part where it is dragged", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      const title = within(drawn).getByText("Draw the map");
      const nav = await outline();
      const handle = screen
        .getAllByRole("button", { name: /move priority/i })
        .find((button) => !nav.contains(button));

      // Dropped on the title's upper half: before it. jsdom lays nothing out,
      // so what is under the pointer is said here.
      const under = document.elementsFromPoint;
      document.elementsFromPoint = () => [title];
      try {
        fireEvent.pointerDown(handle as Element);
        fireEvent.pointerUp(window, { clientX: 0, clientY: 0 });
      } finally {
        document.elementsFromPoint = under;
      }
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      const card = saves[0].views.find((view) => view.slug === "board")?.definition.card;
      expect((card?.children?.[0] as ViewNode | undefined)?.children?.slice(0, 2)).toEqual([
        { type: "field", props: { field: "priority" } },
        { type: "field", props: { field: "title" } },
      ]);
    });
  });

  describe("the set of views", () => {
    const viewPicker = () => screen.getByRole("combobox", { name: /view being edited/i });

    it("adds a view, and keeps it open once the server names it", async () => {
      const { user } = editor("board");
      await outline();

      await user.click(screen.getByRole("button", { name: /add a view/i }));
      expect(viewPicker()).toHaveTextContent("New view");
      const name = screen.getByLabelText(/^name$/i);
      await user.clear(name);
      await user.type(name, "Sprint{Enter}");
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(saves[0].views.at(-1)).toEqual({
        name: "Sprint",
        is_default: false,
        definition: { layout: { type: "board" } },
      });
      expect(await screen.findByRole("button", { name: /^save$/i })).toBeDisabled();
      expect(viewPicker()).toHaveTextContent("Sprint");
    });

    it("deletes the default view and passes the default on", async () => {
      const { user } = editor("table");
      await outline();

      await user.click(screen.getByRole("button", { name: /more for this view/i }));
      await user.click(await screen.findByRole("menuitem", { name: /delete/i }));
      expect(viewPicker()).toHaveTextContent("Board");
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(saves[0].views.map((view) => [view.slug, view.is_default])).toEqual([
        ["board", true],
        ["calendar", false],
        ["incomplete", false],
        ["unassigned", false],
        ["mine", false],
      ]);
    });

    it("names a copy of a long-named view within the limit", async () => {
      const long = "Q".repeat(100);
      const { user } = editor(
        "long",
        vi.fn(),
        buildToolViewSet({
          views: [buildToolView({ slug: "long", name: long, is_default: true })],
        })
      );
      await outline();

      await user.click(screen.getByRole("button", { name: /more for this view/i }));
      await user.click(await screen.findByRole("menuitem", { name: /duplicate/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      const copy = saves[0].views.at(-1)?.name ?? "";
      expect(copy).toMatch(/^Q+… copy$/);
      expect(copy.length).toBe(100);
    });

    it("keeps open the view opened while a save was under way", async () => {
      let answer = () => {};
      server.use(
        communityHttp.put("/views/", async ({ request }) => {
          const body = (await request.json()) as ToolViewSetWrite;
          saves.push(body);
          await new Promise<void>((resolve) => {
            answer = resolve;
          });
          return HttpResponse.json(buildSavedViewSet(body));
        })
      );
      const { user } = editor("board");
      await outline();

      await user.click(screen.getByRole("button", { name: /add a view/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));
      await screen.findByRole("button", { name: /saving/i });
      await user.click(viewPicker());
      await user.click(await screen.findByRole("option", { name: "Table" }));
      answer();

      expect(await screen.findByRole("button", { name: /^save$/i })).toBeDisabled();
      expect(viewPicker()).toHaveTextContent("Table");
    });

    it("stores the filters a view is fixed to", async () => {
      const { user } = editor("board");
      await outline();

      await user.click(screen.getByRole("switch", { name: /show archived/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(
        saves[0].views.find((view) => view.slug === "board")?.definition.filters
      ).toMatchObject({ include_archived: true });
    });
  });

  describe("the task page", () => {
    it("moves a field taken off it to More fields, and stores the page whole", async () => {
      const { user } = editor(TASK_PAGE);
      expect(await within(await canvas()).findByDisplayValue("Draw the map")).toBeInTheDocument();

      await user.click(
        within(await outline()).getByRole("button", { name: /move tags to more fields/i })
      );

      expect(within(await outline()).getByText("More fields")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => expect(saves).toHaveLength(1));
      const [layout] = saves[0].item_layouts ?? [];
      expect(layout?.item_kind).toBe("task");
      expect(JSON.stringify(layout?.definition.side)).not.toContain('"tags"');
      expect(JSON.stringify(layout?.definition)).not.toContain('"order"');
    });

    it("adds a section where it was asked for, titled as typed", async () => {
      const { user } = editor(TASK_PAGE);

      await user.click(
        await within(await outline()).findByRole("button", { name: "Side", pressed: false })
      );
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      await user.click(await screen.findByRole("button", { name: "Section" }));
      await user.type(screen.getByLabelText(/^title$/i), "Planning{Enter}");
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(saves[0].item_layouts?.[0]?.definition.side?.at(-1)).toEqual({
        type: "section",
        props: { title: "Planning" },
        children: [],
      });
    });

    it("goes back to the shipped page", async () => {
      const { user } = editor(
        TASK_PAGE,
        vi.fn(),
        buildToolViewSet({
          item_layouts: [
            { id: 1, item_kind: "task", definition: { main: [{ type: "comments" }] } },
          ],
        })
      );

      await user.click(await screen.findByRole("button", { name: /use the shipped page/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saves).toHaveLength(1));
      expect(saves[0].item_layouts).toEqual([]);
    });
  });
});

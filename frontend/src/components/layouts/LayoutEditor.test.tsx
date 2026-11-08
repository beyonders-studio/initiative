/**
 * The layout editor, worked as a manager works it: change the open layout in
 * the outline or on the canvas, see it at once, and nothing is stored until
 * Save, which sends only the layouts that changed.
 */
import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCalendarEvent,
  buildCollection,
  buildCollectionFile,
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildPropertyOption,
  buildSavedLayoutSet,
  buildTask,
  buildTaskListResponse,
  buildToolLayoutSet,
  TASK_GROUPINGS,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { definitionsHandler } from "@/__tests__/helpers/handlers/property.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type CollectionRead,
  type DetailLayoutWrite,
  type ListLayoutWrite,
  MetadataType,
  Tool,
  type ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import { instanceTarget, sharedTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { MAX_PRESETS } from "@/lib/layouts/presets";
import { TASK_COLUMNS } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";
import { CollectionLayoutEditorPage } from "@/pages/initiativeTools/files/CollectionLayoutEditorPage";

import { calendarPresets, eventDetail, taskDetails, taskPresets } from "./details";
import { LayoutEditor } from "./LayoutEditor";

const STATUSES = buildDefaultTaskStatuses(1);
const TASK_TYPE = {
  id: 1,
  project_id: 1,
  name: "Task",
  position: 0,
  is_default: true,
  hidden: false,
  color: "#94A3B8",
  icon: "square-check",
  layout_preset: "plain",
  starting_values: null,
};
const PROJECT = { id: 1, initiativeId: 1, statuses: STATUSES, types: [TASK_TYPE] };
const PROJECT_DETAILS = taskDetails(PROJECT);
const CALENDAR_DETAILS = [eventDetail(1)];
const PROJECT_PRESETS = taskPresets(PROJECT);
const CALENDAR_PRESETS = calendarPresets(1);

type Write = ListLayoutWrite | DetailLayoutWrite;

/** Each request a save made, in order: a layout saved, one put back as
 *  shipped, or the list the project opens on. */
let sent: Array<{ save: Write } | { reset: string } | { opensOn: string }> = [];

/** What the save of `kind` stored. */
const saved = (kind: string) =>
  sent.flatMap((each) => ("save" in each && each.save.kind === kind ? [each.save] : []))[0]
    ?.definition as Record<string, unknown> | undefined;

/** The editor as its page holds it: on the project's layouts as read, which
 *  each save writes its answer over. With `calendar`, on the initiative
 *  calendar's instead. */
const editor = (kind: string, onClose = vi.fn(), set = buildToolLayoutSet(), calendar = false) => {
  server.use(communityHttp.get("/layouts/", () => HttpResponse.json(set)));
  const target = calendar ? sharedTarget(Tool.calendar, 1) : instanceTarget(Tool.project, 1);
  const Page = () => {
    const read = useToolLayouts(target).data;
    return read ? (
      <LayoutEditor
        target={target}
        initiativeId={1}
        project={calendar ? undefined : PROJECT}
        details={calendar ? CALENDAR_DETAILS : PROJECT_DETAILS}
        presets={calendar ? CALENDAR_PRESETS : PROJECT_PRESETS}
        set={read}
        initialKind={kind}
        ownPropertiesEditable={!calendar}
        onClose={onClose}
      />
    ) : null;
  };
  renderPage(Page);
  return { user: userEvent.setup(), onClose };
};

/** A pointer event from one pointer: jsdom's stand-in carries no id. */
const firePointer = (
  type: "pointerDown" | "pointerUp" | "pointerCancel",
  target: Element | Window,
  pointerId: number
) => {
  const event = createEvent[type](target);
  Object.defineProperty(event, "pointerId", { value: pointerId });
  fireEvent(target, event);
};

const outline = () => screen.findByRole("navigation", { name: /outline/i });

/** A plug-in placed on the initiative's tasks, with a field of its own. */
const ciPlugin = communityHttp.get("/plugins/", () =>
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
);
const canvas = () => screen.findByRole("region", { name: /preview/i });

beforeEach(() => {
  sent = [];
  server.use(
    // Ahead of the one task, which its path would otherwise match.
    communityHttp.get("/tasks/groups", () => HttpResponse.json({ groups: [], rows: {} })),
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
    definitionsHandler([buildPropertyDefinition({ id: 12, name: "Effort" })]),
    communityHttp.put("/layouts/", async ({ request }) => {
      const body = (await request.json()) as Write;
      sent.push({ save: body });
      return HttpResponse.json(buildSavedLayoutSet(buildToolLayoutSet(), body));
    }),
    communityHttp.delete("/layouts/:kind", ({ params, request }) => {
      const typed = new URL(request.url).searchParams.get("task_type_id");
      sent.push({ reset: typed ? `${String(params.kind)}:${typed}` : String(params.kind) });
      return HttpResponse.json(buildToolLayoutSet());
    }),
    communityHttp.put("/layouts/default", async ({ request }) => {
      const { kind } = (await request.json()) as { kind: string };
      sent.push({ opensOn: kind });
      return HttpResponse.json<ToolLayoutSetRead>(buildToolLayoutSet());
    })
  );
});

describe("LayoutEditor", () => {
  it("takes a field off the card at once, and stores it only on Save", async () => {
    const { user } = editor("board");
    expect(await within(await canvas()).findByText(/priority: medium/i)).toBeInTheDocument();
    // A card requires nothing: only an item's page does.
    expect(within(await outline()).queryByRole("button", { name: /required/i })).toBeNull();

    await user.click(within(await outline()).getByRole("button", { name: /hide priority/i }));

    expect(within(await canvas()).queryByText(/priority: medium/i)).not.toBeInTheDocument();
    expect(sent).toEqual([]);
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(JSON.stringify(saved("board")?.card)).not.toContain('"priority"');
    // The other layouts are not sent, so they keep their dates.
    expect(sent).toHaveLength(1);
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
    await user.click(await screen.findByRole("button", { name: /^effort/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(saved("table")?.columns).toEqual([
      "title",
      "assignees",
      "startDate",
      "dueDate",
      "priority",
      "tags",
      "comments",
      "property:12",
    ]);
  });

  it("offers the project's properties and the initiative's metadata under whose they are", async () => {
    server.use(
      definitionsHandler([buildPropertyDefinition({ id: 12, name: "Effort" })], {
        project: [buildPropertyDefinition({ id: 14, name: "Sprint", project_id: 1 })],
      })
    );
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    const picker = await screen.findByRole("dialog", { name: "Add" });
    const sprint = await within(picker).findByRole("button", { name: "Sprint" });
    expect(sprint.parentElement).toHaveTextContent("This project's properties");
    const effort = within(picker).getByRole("button", { name: "Effort" });
    expect(effort.parentElement).toHaveTextContent("Initiative metadata");
    expect(effort.parentElement).not.toHaveTextContent("Sprint");
    await user.click(sprint);
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(saved("table")?.columns).toContain("property:14");
  });

  it("manages the project's properties only where the server says it may", async () => {
    server.use(
      definitionsHandler([buildPropertyDefinition({ id: 12, name: "Effort" })], {
        project: [buildPropertyDefinition({ id: 14, name: "Sprint", project_id: 1 })],
      })
    );
    const { user } = editor("table");

    // With the layout selected, the panel lists them, to change.
    const panel = (await screen.findByRole("heading", { name: "Properties" })).closest(
      "section"
    ) as HTMLElement;
    expect(await within(panel).findByText("Sprint")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Edit property" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "New property" })).toBeInTheDocument();

    // The initiative's metadata is placed here and edited in its settings.
    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    await user.click(await screen.findByRole("button", { name: "Effort" }));
    expect(
      await screen.findByRole("link", { name: "Open initiative settings" })
    ).toBeInTheDocument();
  });

  it("lists the project's properties and changes nothing without the right to", async () => {
    server.use(
      definitionsHandler([], {
        project: [buildPropertyDefinition({ id: 14, name: "Sprint", project_id: 1 })],
      })
    );
    server.use(communityHttp.get("/layouts/", () => HttpResponse.json(buildToolLayoutSet())));
    const target = instanceTarget(Tool.project, 1);
    const Page = () => {
      const read = useToolLayouts(target).data;
      return read ? (
        <LayoutEditor
          target={target}
          initiativeId={1}
          project={PROJECT}
          details={PROJECT_DETAILS}
          presets={PROJECT_PRESETS}
          set={read}
          initialKind="table"
          onClose={vi.fn()}
        />
      ) : null;
    };
    renderPage(Page);

    const panel = (await screen.findByRole("heading", { name: "Properties" })).closest(
      "section"
    ) as HTMLElement;
    expect(await within(panel).findByText("Sprint")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Edit property" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "New property" })).not.toBeInTheDocument();
  });

  it("makes a new field the project's property, or the initiative's metadata if asked", async () => {
    const made: Record<string, unknown>[] = [];
    server.use(
      communityHttp.post("/property-definitions/", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        made.push(body);
        return HttpResponse.json(
          buildPropertyDefinition({ id: 40 + made.length, name: String(body.name) })
        );
      })
    );
    const { user } = editor("table");

    const add = async (name: string, initiatives: boolean) => {
      await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.type(within(picker).getByRole("textbox", { name: /search/i }), name);
      await user.click(within(picker).getByRole("button", { name: /^text$/i }));
      expect(within(picker).getByRole("combobox", { name: "Belongs to" })).toHaveTextContent(
        "This project's properties"
      );
      if (initiatives) {
        await user.click(within(picker).getByRole("combobox", { name: "Belongs to" }));
        await user.click(await screen.findByRole("option", { name: "The initiative's metadata" }));
      }
      await user.click(within(picker).getByRole("button", { name: /^create$/i }));
    };
    await add("Sprint", false);
    await add("Budget", true);

    await waitFor(() => expect(made).toHaveLength(2));
    expect(made[0]).toMatchObject({ name: "Sprint", initiative_id: 1, project_id: 1 });
    expect(made[1]).toMatchObject({ name: "Budget", initiative_id: 1 });
    expect(made[1]).not.toHaveProperty("project_id");
  });

  it("names the part showing every value for the project's properties too", async () => {
    editor("board");

    // The shipped card holds it.
    expect(
      await within(await outline()).findByRole("button", { name: "All properties and metadata" })
    ).toBeInTheDocument();
  });

  it("draws a scale column as the layout picks", async () => {
    server.use(
      definitionsHandler([
        buildPropertyDefinition({ id: 13, name: "Score", type: MetadataType.scale }),
      ])
    );
    const { user } = editor("table");

    await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
    await user.click(await screen.findByRole("button", { name: /^score/i }));
    // What was added is selected, and its settings say how it is drawn.
    await user.click(screen.getByRole("combobox", { name: /show the scale as/i }));
    await user.click(await screen.findByRole("option", { name: "Stars" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(saved("table")?.displays).toEqual({ "property:13": "stars" });
  });

  it("changes nothing while a save is under way, and still asks before leaving", async () => {
    let answer = () => {};
    server.use(
      communityHttp.put("/layouts/", async ({ request }) => {
        const body = (await request.json()) as Write;
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return HttpResponse.json(buildSavedLayoutSet(buildToolLayoutSet(), body));
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

  it("shows a placed plug-in's field on a table as shipped, and takes it off", async () => {
    server.use(ciPlugin);
    const { user } = editor("table");

    // It shows as it arrives, after the shipped columns; taken off, it stays off.
    await user.click(await within(await outline()).findByRole("button", { name: /^hide build/i }));
    expect(within(await outline()).queryByRole("button", { name: /required/i })).toBeNull();
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(saved("table")?.columns).toEqual(TASK_COLUMNS);
  });

  it("shows a list, and opens the project on it, as changes of their own", async () => {
    const { user } = editor("gantt", vi.fn(), buildToolLayoutSet({ hidden: ["gantt"] }));
    await outline();

    // A hidden list is not one to open on, and the last one shown stays shown.
    expect(screen.queryByRole("switch", { name: /opens first/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: /shown in the layout menu/i }));
    await user.click(screen.getByRole("switch", { name: /opens first/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(sent).toEqual([
        { save: { kind: "gantt", definition: { hidden: false } } },
        { opensOn: "gantt" },
      ])
    );
  });

  it("keeps the last list a project shows", async () => {
    editor("board", vi.fn(), buildToolLayoutSet({ hidden: ["table", "gantt", "calendar"] }));
    await outline();

    expect(screen.getByRole("switch", { name: /shown in the layout menu/i })).toBeDisabled();
  });

  it("adds a preset to the open list beside the shipped ones, sorted as chosen", async () => {
    const { user } = editor("table");
    await outline();

    await user.click(screen.getByRole("button", { name: /add preset/i }));
    const dialog = await screen.findByRole("dialog", { name: /add a preset/i });
    await user.type(within(dialog).getByLabelText(/^name$/i), "Overdue first");
    await user.click(within(dialog).getByRole("combobox", { name: /sort by/i }));
    await user.click(await screen.findByRole("option", { name: /due date/i }));
    await user.click(within(dialog).getByRole("switch", { name: /descending/i }));
    await user.click(within(dialog).getByRole("button", { name: /^done$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("table")).toBeDefined());
    const presets = saved("table")?.presets as Record<string, unknown>[];
    // The shipped ones are kept by slug alone, so each reader still reads
    // their names in their own words.
    expect(presets.map((preset) => [preset.slug, preset.name])).toEqual([
      ["incomplete", undefined],
      ["unassigned", undefined],
      ["mine", undefined],
      ["overdue-first", "Overdue first"],
    ]);
    expect(presets[3].sort).toEqual([{ field: "due_date", dir: "desc" }]);
  });

  it("adds no preset past the most a list may offer", async () => {
    const presets = Array.from({ length: MAX_PRESETS }, (_, index) => ({
      name: `Preset ${index}`,
      slug: `preset-${index}`,
    }));
    editor(
      "table",
      vi.fn(),
      buildToolLayoutSet({
        layouts: [
          {
            kind: "table",
            is_default: true,
            hidden: false,
            definition: { presets },
            updated_at: "2026-10-01T12:00:00.000Z",
          },
        ],
      })
    );
    await outline();

    expect(screen.getByRole("button", { name: /add preset/i })).toBeDisabled();
    expect(screen.getByText(/at most 20 presets/i)).toBeInTheDocument();
  });

  it("takes a preset off the open list and keeps the rest in order", async () => {
    const { user } = editor("board");
    await outline();

    await user.click(screen.getByRole("button", { name: /move mine up/i }));
    await user.click(screen.getByRole("button", { name: /remove incomplete/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("board")).toBeDefined());
    const presets = saved("board")?.presets as { slug: string }[] | undefined;
    expect(presets?.map((preset) => preset.slug)).toEqual(["mine", "unassigned"]);
  });

  it("offers a property's grouping once it is ticked, and starts the table on it", async () => {
    server.use(
      definitionsHandler([
        buildPropertyDefinition({
          id: 12,
          name: "Sprint",
          type: MetadataType.select,
          options: [buildPropertyOption({ value: "s1", label: "Sprint 1" })],
        }),
      ])
    );
    const { user } = editor("table");
    await outline();

    await user.click(await screen.findByRole("checkbox", { name: "Sprint" }));
    await user.click(screen.getByRole("combobox", { name: /starts grouped by/i }));
    await user.click(await screen.findByRole("option", { name: "Sprint" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("table")).toBeDefined());
    expect(saved("table")?.groupings).toEqual([
      ...TASK_GROUPINGS.filter((entry) => !entry.bucket).map((entry) => ({ field: entry.name })),
      { field: "property:12" },
    ]);
    expect(saved("table")?.group_by).toBe("property:12");
  });

  it("leaves out a group clicked above the grouped preview", async () => {
    server.use(
      communityHttp.get("/tasks/groups", () =>
        HttpResponse.json({
          groups: STATUSES.map((status) => ({ key: String(status.id), label: status.name })),
          rows: {},
        })
      )
    );
    const { user } = editor(
      "table",
      vi.fn(),
      buildToolLayoutSet({
        layouts: [
          {
            kind: "table",
            is_default: true,
            hidden: false,
            definition: { group_by: "task_status_id" },
            updated_at: "2026-10-01T12:00:00.000Z",
          },
        ],
      })
    );
    await outline();

    const done = await screen.findByRole("button", { name: "Done", pressed: true });
    await user.click(done);
    expect(done).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("table")).toBeDefined());
    const groupings = saved("table")?.groupings as { field: string; hidden?: string[] }[];
    expect(groupings.find((entry) => entry.field === "task_status_id")?.hidden).toEqual([
      String(STATUSES[2].id),
    ]);
  });

  it("limits a board's column, takes the limit off when emptied, and refuses one past the most", async () => {
    const { user } = editor("board");
    await outline();
    const [, doing, done] = STATUSES;

    const limit = await screen.findByRole("spinbutton", { name: doing.name });
    await user.type(limit, "4");
    await user.tab();
    await user.type(screen.getByRole("spinbutton", { name: done.name }), "2");
    await user.tab();
    await user.clear(screen.getByRole("spinbutton", { name: done.name }));
    await user.tab();
    // More than a column may take puts back what it had.
    await user.type(screen.getByRole("spinbutton", { name: done.name }), "10001");
    await user.tab();
    expect(screen.getByRole("spinbutton", { name: done.name })).toHaveValue(null);
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("board")).toBeDefined());
    expect(saved("board")?.limits).toEqual([{ status_id: doing.id, limit: 4 }]);
  });

  it("offers presets on the calendar's list, with the calendar's own filters", async () => {
    const { user } = editor("calendar", vi.fn(), buildToolLayoutSet({ tool: "calendar" }), true);

    await user.click(await screen.findByRole("button", { name: /add preset/i }));
    const dialog = await screen.findByRole("dialog", { name: /add a preset/i });
    await user.type(within(dialog).getByLabelText(/^name$/i), "Urgent");
    // Its filters are the calendar's: no assignees, and no sort.
    expect(within(dialog).queryByRole("combobox", { name: /assignee/i })).toBeNull();
    expect(within(dialog).queryByRole("combobox", { name: /sort by/i })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: /^done$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saved("calendar")).toBeDefined());
    expect(saved("calendar")?.presets).toEqual([
      expect.objectContaining({ name: "Urgent", slug: "urgent", sort: [] }),
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
      await user.click(within(picker).getByRole("button", { name: /^row/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      // The row holding Priority starts with the new row, Priority after it.
      expect(
        (
          (card as LayoutNode | undefined)?.children?.[1] as LayoutNode | undefined
        )?.children?.slice(0, 2)
      ).toEqual([
        { type: "stack", props: { direction: "row", wrap: true }, children: [] },
        { type: "field", props: { field: "priority" } },
      ]);
    });

    it("adds a column after the one pointed at", async () => {
      const { user } = editor("table");
      const header = await within(await canvas()).findByRole("columnheader", { name: /priority/i });
      await user.hover(within(header).getByText(/priority/i));

      fireEvent.click(screen.getByRole("button", { name: /add after priority/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: /^effort/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(saved("table")?.columns).toEqual([
        "title",
        "assignees",
        "startDate",
        "dueDate",
        "priority",
        "property:12",
        "tags",
        "comments",
      ]);
    });

    /** Grabs the selected part's handle on the canvas, with one pointer. */
    const grab = async (name: RegExp, pointer = 1) => {
      const nav = await outline();
      const handle = screen
        .getAllByRole("button", { name })
        .find((button) => !nav.contains(button)) as Element;
      firePointer("pointerDown", handle, pointer);
    };
    /** What jsdom cannot work out: the element under the pointer. */
    const under = (element: Element, run: () => void) => {
      const was = document.elementsFromPoint;
      document.elementsFromPoint = () => [element];
      try {
        run();
      } finally {
        document.elementsFromPoint = was;
      }
    };

    it("lets a drag go when an undo changes the card under it", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(within(await outline()).getByRole("button", { name: /hide tags/i }));
      await user.click(await within(drawn).findByText(/priority: medium/i));
      await grab(/move priority/i);

      await user.keyboard("{Control>}z{/Control}");
      under(within(drawn).getByText("Draw the map"), () => firePointer("pointerUp", window, 1));

      // The undo stands, and nothing moved after it.
      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("moves a part only for the pointer that took hold of it", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      const title = within(drawn).getByText("Draw the map");

      await grab(/move priority/i, 1);
      under(title, () => firePointer("pointerUp", window, 2));
      firePointer("pointerCancel", window, 1);
      under(title, () => firePointer("pointerUp", window, 1));

      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("takes a part into a row added empty", async () => {
      const { user } = editor("board");
      const drawn = await canvas();
      await user.click(await within(drawn).findByText(/priority: medium/i));
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.click(within(picker).getByRole("button", { name: /^row/i }));
      // Adding put the row after Priority and selected it; Priority again.
      await user.click(within(drawn).getByText(/priority: medium/i));
      const [empty] = within(drawn).getAllByText(/drop a part here/i);
      await user.hover(empty);
      expect(screen.getByRole("button", { name: /add to row/i })).toBeInTheDocument();

      await grab(/move priority/i);
      under(empty, () => firePointer("pointerUp", window, 1));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      expect(
        ((card as LayoutNode | undefined)?.children?.[1] as LayoutNode | undefined)?.children?.[0]
      ).toEqual({
        type: "stack",
        props: { direction: "row", wrap: true },
        children: [{ type: "field", props: { field: "priority" } }],
      });
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

      await waitFor(() => expect(sent).toHaveLength(1));
      const card = saved("board")?.card;
      // Into the row the title shares with its type's icon.
      const first = (card as LayoutNode | undefined)?.children?.[0] as LayoutNode | undefined;
      const row = first?.children?.find((node) =>
        (node as LayoutNode).children?.some((child) => child.props?.field === "title")
      ) as LayoutNode | undefined;
      expect(row?.children).toEqual([
        { type: "field", props: { field: "type" } },
        { type: "field", props: { field: "priority" } },
        { type: "field", props: { field: "title" } },
      ]);
    });
  });

  describe("the task's detail", () => {
    it("hides a field taken off it, and stores the layout whole", async () => {
      const { user } = editor("task:1");
      expect(await within(await canvas()).findByDisplayValue("Draw the map")).toBeInTheDocument();

      await user.click(within(await outline()).getByRole("button", { name: /^hide tags$/i }));

      expect(within(await outline()).queryByText("Tags")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("task")?.side)).not.toContain('"tags"');
      expect(JSON.stringify(saved("task"))).not.toContain('"order"');
    });

    it("makes a new field of the kind picked and places it", async () => {
      const made: Record<string, unknown>[] = [];
      server.use(
        communityHttp.post("/property-definitions/", async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          made.push(body);
          return HttpResponse.json(
            buildPropertyDefinition({ id: 31, name: String(body.name), type: "number" })
          );
        })
      );
      const { user } = editor("task:1");

      await user.click(
        await within(await outline()).findByRole("button", { name: "Side", pressed: false })
      );
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      // A search no kind matches keeps every kind, and names the field.
      await user.type(within(picker).getByRole("textbox", { name: /search/i }), "Budget");
      await user.click(within(picker).getByRole("button", { name: /^number$/i }));
      expect(within(picker).getByLabelText(/^Name$/)).toHaveValue("Budget");
      await user.click(within(picker).getByRole("button", { name: /^create$/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(made).toEqual([expect.objectContaining({ name: "Budget", type: "number" })]);
      expect((saved("task")?.side as LayoutNode[] | undefined)?.at(-1)).toEqual({
        type: "field",
        props: { field: "property:31" },
      });
    });

    it("places a property on its own", async () => {
      const { user } = editor("task:1");

      await user.click(
        await within(await outline()).findByRole("button", { name: "Side", pressed: false })
      );
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      await user.click(
        within(await screen.findByRole("dialog", { name: "Add" })).getByRole("button", {
          name: /^effort/i,
        })
      );
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect((saved("task")?.side as LayoutNode[] | undefined)?.at(-1)).toEqual({
        type: "field",
        props: { field: "property:12" },
      });
    });

    it("adds accordions where asked for, each named by typing over its title", async () => {
      const { user } = editor("task:1");

      await user.click(
        await within(await outline()).findByRole("button", { name: "Side", pressed: false })
      );
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      // The search narrows what is offered.
      await user.type(within(picker).getByRole("textbox", { name: /search/i }), "acc");
      expect(within(picker).queryByRole("button", { name: /^row/i })).not.toBeInTheDocument();
      await user.click(within(picker).getByRole("button", { name: /^accordion/i }));
      // Its title is selected as it opens, so typing names it.
      await user.keyboard("Planning{Enter}");
      // Another, added while the first is still selected, is named the same way.
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      await user.click(
        within(await screen.findByRole("dialog", { name: "Add" })).getByRole("button", {
          name: /^accordion/i,
        })
      );
      await user.keyboard("Later{Enter}");
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      // The second went into the first, which was selected.
      expect((saved("task")?.side as LayoutNode[] | undefined)?.at(-1)).toEqual({
        type: "section",
        props: { title: "Planning" },
        children: [{ type: "section", props: { title: "Later" }, children: [] }],
      });
    });

    it("requires a field from its row in the outline, and shows a title as always", async () => {
      server.use(ciPlugin);
      const { user } = editor("task:1");
      const required = async (name: string) =>
        within(await outline()).queryByRole("button", { name: new RegExp(`^${name}: `) });

      const tags = await required("Tags");
      expect(tags).toHaveAccessibleName("Tags: not required. Press to require it.");
      expect(tags).toHaveAttribute("aria-pressed", "false");
      await user.click(tags as HTMLElement);
      expect(await required("Tags")).toHaveAttribute("aria-pressed", "true");
      // A part of the page's own that edits a field can be too.
      await user.click((await required("When")) as HTMLElement);
      // Pressed twice, it is not required again.
      await user.click((await required("When")) as HTMLElement);

      const title = await required("Task");
      expect(title).toHaveAccessibleName("Task: required. A title is always required.");
      expect(title).toHaveAttribute("aria-pressed", "true");
      expect(title).toHaveAttribute("aria-disabled", "true");
      // It still takes focus, so its explanation opens from the keyboard, and
      // pressing it changes nothing.
      (title as HTMLElement).focus();
      expect(title).toHaveFocus();
      await user.click(title as HTMLElement);
      expect(await required("Task")).toHaveAttribute("aria-pressed", "true");
      // What nobody fills in, what is never empty, and what a plug-in fills
      // cannot be.
      expect(await within(await outline()).findByRole("button", { name: "Build" })).toBeVisible();
      for (const part of ["Created by", "Status", "Build"]) {
        expect(await required(part)).not.toBeInTheDocument();
      }
      // The part's settings hold no second control.
      await user.click(within(await outline()).getByRole("button", { name: "Tags" }));
      expect(screen.queryByRole("switch", { name: /required/i })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /^save$/i }));
      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("task"))).toContain('{"field":"tags","required":true}');
      expect(JSON.stringify(saved("task"))).not.toContain('{"field":"title","required"');
      expect(JSON.stringify(saved("task"))).not.toContain('"type":"dates","props":{"required"');
    });

    it("explains a requirement in its tooltip", async () => {
      const { user } = editor("task:1");

      await user.hover(
        within(await outline()).getByRole("button", { name: /^Tags: not required/ })
      );
      expect(await screen.findByRole("tooltip")).toHaveTextContent(
        /Not required\. Press to require it\.Whoever adds one has to fill this in/
      );
    });

    it("takes the flag off with the field it hides", async () => {
      const { user } = editor(
        "task:1",
        vi.fn(),
        buildToolLayoutSet({
          layouts: [
            {
              kind: "task",
              task_type_id: 1,
              task_type_name: "Task",
              definition: { side: [{ type: "field", props: { field: "tags", required: true } }] },
              updated_at: "2026-10-01T12:00:00.000Z",
            },
          ],
        })
      );

      await user.click(within(await outline()).getByRole("button", { name: /^hide tags$/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("task"))).not.toContain("required");
    });

    it("goes back to the shipped layout", async () => {
      const { user } = editor(
        "task:1",
        vi.fn(),
        buildToolLayoutSet({
          layouts: [
            {
              kind: "task",
              task_type_id: 1,
              task_type_name: "Task",
              definition: { main: [{ type: "comments" }] },
              updated_at: "2026-10-01T12:00:00.000Z",
            },
          ],
        })
      );

      await user.click(await screen.findByRole("button", { name: /use the shipped layout/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toEqual([{ reset: "task:1" }]));
    });
  });

  describe("the calendar's event detail", () => {
    it("lays out the event detail alone, sending it and nothing else", async () => {
      const event = buildCalendarEvent({ id: 9, title: "Standup", location: "Room 2" });
      server.use(
        communityHttp.get("/calendar-entries/", () =>
          HttpResponse.json({ events: [event], tasks: [], task_occurrences: [] })
        ),
        communityHttp.get("/calendar-events/:eventId", () => HttpResponse.json(event))
      );
      const { user } = editor("", vi.fn(), buildToolLayoutSet({ tool: "calendar" }), true);
      expect(await within(await canvas()).findByDisplayValue("Room 2")).toBeInTheDocument();

      await user.click(within(await outline()).getByRole("button", { name: /^hide location$/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(JSON.stringify(saved("calendar_event"))).not.toContain('"location"');
    });
  });

  describe("a collection's layouts", () => {
    /** The collection's layouts page, for `collection` (id 5) holding one file. */
    const collectionEditor = (collection: CollectionRead) => {
      server.use(
        communityHttp.get("/collections/:id", () => HttpResponse.json(collection)),
        communityHttp.get("/collections/:id/files", () =>
          HttpResponse.json({
            items: [buildCollectionFile({ id: 4, name: "Harbour" })],
            total_count: 1,
            page: 1,
            page_size: 60,
            has_next: false,
            has_prev: false,
          })
        ),
        communityHttp.get("/layouts/", () =>
          HttpResponse.json(
            buildToolLayoutSet({ tool: "collection", hidden: ["masonry", "timeline"] })
          )
        )
      );
      renderPage(CollectionLayoutEditorPage, {
        initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId/layouts",
        routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
      });
      return userEvent.setup();
    };

    it("puts the collection's property on a wall's card, drawn as stars", async () => {
      const rating = buildPropertyDefinition({
        id: 31,
        name: "Stars given",
        type: MetadataType.scale,
        collection_id: 5,
      });
      server.use(definitionsHandler([], { collection: [rating] }));
      const user = collectionEditor(buildCollection({ id: 5, metadata: [rating] }));

      // Beside the layout, the collection's properties, each saying where it
      // shows: the file's page shows every one.
      expect(await screen.findByText("Shown on File page")).toBeInTheDocument();

      await user.click(await within(await outline()).findByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      // Listed under whose it is.
      const field = await within(picker).findByRole("button", { name: "Stars given" });
      expect(field.parentElement).toHaveTextContent("This collection's properties");
      await user.click(field);
      await user.click(screen.getByRole("combobox", { name: /show the scale as/i }));
      await user.click(await screen.findByRole("option", { name: "Stars" }));
      await user.click(within(await outline()).getByRole("button", { name: "Grid" }));
      expect(await screen.findByText("Shown on Grid and File page")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saved("grid")).toBeDefined());
      expect(saved("grid")).toMatchObject({
        card: { type: "card", children: [{ type: "field", props: { field: "property:31" } }] },
        displays: { "property:31": "stars" },
      });
    });

    it("makes a property of the collection's on a file's page and places it", async () => {
      const made: Record<string, unknown>[] = [];
      server.use(
        communityHttp.post("/property-definitions/", async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          made.push(body);
          return HttpResponse.json(
            buildPropertyDefinition({ id: 32, name: String(body.name), collection_id: 5 }),
            { status: 201 }
          );
        })
      );
      const user = collectionEditor(buildCollection({ id: 5, initiative_id: 1 }));

      await user.click(await screen.findByRole("combobox", { name: "Layout being edited" }));
      await user.click(await screen.findByRole("option", { name: "File page" }));
      // Drawn with the collection's first file.
      expect(
        await within(await canvas()).findByRole("heading", { name: "Harbour" })
      ).toBeInTheDocument();
      await user.click(within(await outline()).getByRole("button", { name: /^add$/i }));
      const picker = await screen.findByRole("dialog", { name: "Add" });
      await user.type(within(picker).getByRole("textbox", { name: /search/i }), "Credit");
      await user.click(within(picker).getByRole("button", { name: /^text$/i }));
      await user.click(within(picker).getByRole("button", { name: /^create$/i }));
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => expect(saved("file")).toBeDefined());
      expect(made).toEqual([
        expect.objectContaining({ name: "Credit", initiative_id: 1, collection_id: 5 }),
      ]);
      expect((saved("file")?.main as LayoutNode[] | undefined)?.at(-1)).toEqual({
        type: "field",
        props: { field: "property:32" },
      });
    });
  });
});

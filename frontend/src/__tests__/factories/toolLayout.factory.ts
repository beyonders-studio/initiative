import type {
  DetailLayoutRead,
  DetailLayoutWrite,
  ListLayoutRead,
  ListLayoutReadKind,
  ListLayoutWrite,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";

/** When a layout built here was last changed. */
const CHANGED = "2026-10-01T12:00:00.000Z";

/** Which layout a layout is: its kind, and a task page's type. */
const sameLayout = (
  a: ListLayoutRead | DetailLayoutRead,
  b: { kind: string; task_type_id?: number | null }
) =>
  a.kind === b.kind &&
  (("task_type_id" in a ? a.task_type_id : null) ?? null) === (b.task_type_id ?? null);

/** A target's layouts as the server reads them until it changes any, each as
 *  shipped: a project's table (which it opens on), board, Gantt and calendar,
 *  every one shown, then
 *  the page of its task type 1, "Task"; with `tool: "calendar"`, the
 *  initiative calendar's calendar and its event's detail; or, with
 *  `tool: "collection"`, a collection's four lists and its file's detail.
 *  `hidden` names lists the target hides, as stored, and it opens on the first still shown.
 *  `layouts` replaces those of the same kind (and type), and another type's
 *  page is added. */
export function buildToolLayoutSet(
  overrides: Partial<Omit<ToolLayoutSetRead, "layouts">> & {
    layouts?: (ListLayoutRead | DetailLayoutRead)[];
    tool?: "project" | "calendar" | "collection";
    hidden?: ListLayoutReadKind[];
  } = {}
): ToolLayoutSetRead {
  const { layouts = [], tool = "project", hidden = [], ...rest } = overrides;
  const lists: ListLayoutReadKind[] =
    tool === "project"
      ? ["table", "board", "gantt", "calendar"]
      : tool === "collection"
        ? ["masonry", "grid", "timeline", "table"]
        : ["calendar"];
  const pages: DetailLayoutRead[] =
    tool === "project"
      ? [
          {
            kind: "task",
            task_type_id: 1,
            task_type_name: "Task",
            definition: {},
            updated_at: null,
          },
        ]
      : [
          {
            kind: tool === "calendar" ? "calendar_event" : "file",
            task_type_id: null,
            task_type_name: null,
            definition: {},
            updated_at: null,
          },
        ];
  // A target shows every list it does not hide, and opens on the first.
  const opensOn = lists.find((kind) => !hidden.includes(kind));
  const shipped: (ListLayoutRead | DetailLayoutRead)[] = [
    ...lists.map((kind) => ({
      kind,
      is_default: kind === opensOn,
      hidden: hidden.includes(kind),
      definition: hidden.includes(kind) ? { hidden: true } : {},
      updated_at: hidden.includes(kind) ? "2026-01-01T00:00:00Z" : null,
    })),
    ...pages,
  ];
  const key = (each: ListLayoutRead | DetailLayoutRead) => ({
    kind: each.kind,
    task_type_id: "task_type_id" in each ? each.task_type_id : null,
  });
  return {
    layouts: [
      ...shipped.map((each) => layouts.find((layout) => sameLayout(layout, key(each))) ?? each),
      // Another task type's page follows the shipped ones.
      ...layouts.filter((layout) => !shipped.some((each) => sameLayout(each, key(layout)))),
    ],
    can_configure: true,
    ...rest,
  };
}

/** `set` as the server answers a change: `write` saved, and dated. */
export function buildSavedLayoutSet(
  set: ToolLayoutSetRead,
  write: ListLayoutWrite | DetailLayoutWrite
): ToolLayoutSetRead {
  return {
    ...set,
    layouts: set.layouts.map((layout) =>
      sameLayout(layout, write)
        ? ({ ...layout, definition: write.definition, updated_at: CHANGED } as typeof layout)
        : layout
    ),
  };
}

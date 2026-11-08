import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPluginCatalogEntry } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { DefinitionWidget } from "@/lib/widgets/definition";

const renderWidget = vi.hoisted(() => vi.fn());
const readWidgetMeta = vi.hoisted(() => vi.fn());
vi.mock("@/lib/widgets/runtime/host", () => ({ renderWidget, readWidgetMeta }));

import { WidgetConfigDialog } from "./WidgetConfigDialog";

const BUILT_SQL = "SELECT count(*) AS count FROM tasks";
const SHIPPED_SQL = "SELECT priority, count(*) AS tasks FROM tasks GROUP BY priority";

const VOCABULARY = {
  datasets: ["tasks", "projects"],
  functions: ["count", "date_trunc", "lower"],
  tokens: ["me"],
};

const FIELD = (name: string, type: string, kind = "text") => ({
  name,
  type,
  kind,
  ops: ["eq"],
  multiple: false,
  sortable: true,
  options: [],
});

/** Every request the two tabs make, counted so a test can say what was asked. */
const asked = { build: 0, describe: 0 };

/** The last description the builder sent, so a test can read what was clicked. */
const described: { build: Record<string, unknown> | null } = { build: null };

const serve = () => {
  asked.build = 0;
  asked.describe = 0;
  described.build = null;
  server.use(
    http.get("/api/v1/query/vocabulary", () => HttpResponse.json(VOCABULARY)),
    http.get("/api/v1/fields/:dataset", ({ params }) =>
      HttpResponse.json({
        dataset: params.dataset,
        fields:
          params.dataset === "tasks"
            ? [
                FIELD("title", "text"),
                FIELD("due_date", "date"),
                FIELD("created_by", "reference", "member"),
              ]
            : [FIELD("name", "text")],
        relations: params.dataset === "tasks" ? [{ name: "project", dataset: "projects" }] : [],
      })
    ),
    communityHttp.post("/query/build", async ({ request }) => {
      asked.build += 1;
      described.build = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({
        sql: BUILT_SQL,
        columns: [],
        relations: ["tasks"],
        // An endpoint's columns, as its plug-in declares them.
        ...(described.build.plugin
          ? {
              plugins: [
                {
                  alias: "plugin",
                  fields: [FIELD("status", "text"), FIELD("total", "number", "number")],
                },
              ],
            }
          : {}),
      });
    }),
    communityHttp.post("/query/describe", async ({ request }) => {
      asked.describe += 1;
      const body = (await request.json()) as { sql: string };
      // The validator refuses a name the registry does not have; everything
      // else in these tests is a statement it accepts.
      if (body.sql.includes("nope")) {
        return HttpResponse.json({ detail: "QUERY_UNKNOWN_FIELD" }, { status: 400 });
      }
      return HttpResponse.json({
        columns: [{ name: "tasks", type: "number" }],
        relations: ["tasks"],
      });
    }),
    communityHttp.post("/query", () =>
      HttpResponse.json({
        columns: [
          { name: "priority", type: "text" },
          { name: "tasks", type: "number" },
        ],
        rows: [["high", 3]],
        truncated: false,
        relations: ["tasks"],
      })
    )
  );
};

const onSave = vi.fn();

beforeEach(() => {
  onSave.mockReset();
  renderWidget.mockReset();
  readWidgetMeta.mockReset();
  renderWidget.mockResolvedValue({ ok: true, spec: { scene: { kind: "empty" } } });
  readWidgetMeta.mockResolvedValue({ name: { en: "Total" } });
  serve();
});

const widget = (binding: WidgetBinding): DefinitionWidget => ({
  id: "w1",
  type: "stat",
  grid: { x: 0, y: 0, w: 6, h: 4 },
  binding,
});

const mount = (which: DefinitionWidget) =>
  renderWithProviders(
    <WidgetConfigDialog
      widget={which}
      catalog={{ widgets: [], presets: [] }}
      initiativeId={7}
      open
      onOpenChange={() => {}}
      onSave={onSave}
    />,
    { communities: { activeCommunityId: 2 } }
  );

const sqlBox = () => screen.getByRole("textbox", { name: /statement/i });

describe("a statement that arrived without a description", () => {
  it("opens on SQL, showing what it has", async () => {
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
  });

  it("is not replaced by the builder's default just by being looked at", async () => {
    // The bug: the builder used to initialise on its default spec, build that,
    // and write it over the author's statement before anybody touched anything.
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));

    expect(asked.build).toBe(0);
  });

  it("says the builder is not driving it, and offers to start over", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await user.click(await screen.findByRole("tab", { name: /build/i }));
    expect(await screen.findByRole("button", { name: /build a new query/i })).toBeInTheDocument();
  });
});

describe("a statement somebody builds", () => {
  it("is written by the server from what was clicked", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("tab", { name: /sql/i }));
    await waitFor(() => expect(sqlBox()).toHaveValue(BUILT_SQL));
  });
});

describe("narrowing what a tile is about", () => {
  it("starts with nothing, which is every row", async () => {
    mount(widget({ source: "query" }));
    expect(await screen.findByText(/no filters/i)).toBeInTheDocument();
  });

  it("sends what was clicked as part of the description", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("button", { name: /add filter/i }));

    await waitFor(() => {
      const where = described.build?.where as { field: string }[] | undefined;
      expect(where?.[0]?.field).toBe("title");
    });
  });

  it("offers nothing to filter on where the dataset named no fields", async () => {
    // A catalog that could not be read looks the same as a dataset with
    // nothing comparable in it, and adding a condition in either case would
    // store one naming no field at all.
    server.use(
      http.get("/api/v1/fields/:dataset", ({ params }) =>
        HttpResponse.json({ dataset: params.dataset, fields: [] })
      )
    );
    mount(widget({ source: "query" }));

    expect(await screen.findByText(/nothing to filter on/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
  });

  it("offers the reader in a picker that holds people", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await user.click(await screen.findByRole("button", { name: /add filter/i }));
    // The first field is text; the person field is what has a member picker.
    await user.click(await screen.findByRole("combobox", { name: /field/i }));
    await user.click(await screen.findByRole("option", { name: /created by/i }));

    await user.click(await screen.findByRole("combobox", { name: /value/i }));
    expect(await screen.findByRole("option", { name: /^me$/i })).toBeInTheDocument();
  });
});

describe("a statement somebody writes", () => {
  it("drops the description behind it, because it is no longer true of it", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " LIMIT 5");

    await waitFor(() => expect(sqlBox()).toHaveValue(`${SHIPPED_SQL} LIMIT 5`));
    // Never handed back to the builder to re-derive: the text is what is stored.
    expect(asked.build).toBe(0);
  });

  it("is checked by the server, and says what it would return", async () => {
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(asked.describe).toBeGreaterThan(0));
    expect(await screen.findByText("Returns: tasks")).toBeInTheDocument();
  });
});

describe("completion", () => {
  /** A widget already on the SQL tab, so typing continues the stored text
   *  rather than the statement the builder would have written. */
  const halfWritten = () => widget({ source: "query", sql: "SELECT " });

  it("offers the names the server says exist", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "ti");
    // `title` is a field of tasks, which the server named in the catalog.
    expect(await screen.findByRole("button", { name: /title/i })).toBeInTheDocument();
  });

  it("offers a dataset and a function too, not only fields", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "co");
    expect(await screen.findByRole("button", { name: /count/i })).toBeInTheDocument();
  });

  it("offers the reader, which is a name no dataset holds", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "m");
    expect(await screen.findByRole("button", { name: /^me$/i })).toBeInTheDocument();
  });

  it("puts the chosen name in place of the word being typed", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "ti");
    await user.click(await screen.findByRole("button", { name: /title/i }));

    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT title"));
  });

  // What the list holds for a given word — a relation beside the dataset that
  // matches the same letters, a related dataset's columns under the relation's
  // name — is the completion library's answer, proved directly in
  // `src/lib/widgets/completion.test.ts`. The tests here are the dialog's side
  // of it: that the catalog the server sent reaches the list, and that
  // choosing an entry lands in the box.

  it("offers nothing once a name is written in full", async () => {
    const user = userEvent.setup();
    mount(halfWritten());

    await user.click(sqlBox());
    await user.type(sqlBox(), "title");
    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT title"));
    expect(screen.queryByRole("button", { name: /^title$/i })).not.toBeInTheDocument();
  });
});

describe("a statement the server refuses", () => {
  const saveButton = () => screen.getByRole("button", { name: /^save$/i });

  it("cannot be saved", async () => {
    // A statement is checked where a definition is normalized, so saving a
    // refused one takes the whole dashboard with it — and the dialog that
    // could fix it has closed by then.
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");

    await waitFor(() => expect(saveButton()).toBeDisabled());
    expect(onSave).not.toHaveBeenCalled();
  });

  it("says so, rather than showing the last good answer", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await screen.findByText("Returns: tasks");
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");

    await waitFor(() => expect(screen.queryByText("Returns: tasks")).not.toBeInTheDocument());
  });

  it("can be saved once it is corrected", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.click(sqlBox());
    await user.type(sqlBox(), " nope");
    await waitFor(() => expect(saveButton()).toBeDisabled());

    await user.type(sqlBox(), "{backspace}{backspace}{backspace}{backspace}{backspace}");
    await waitFor(() => expect(saveButton()).toBeEnabled());

    await user.click(saveButton());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        binding: expect.objectContaining({ source: "query", sql: SHIPPED_SQL }),
      })
    );
  });

  it("does not block a widget with no statement at all", async () => {
    // The state a widget is in before anybody points it anywhere. It stores
    // fine, and the canvas draws it as one asking to be configured.
    mount(widget({ source: "query", sql: SHIPPED_SQL }));
    const user = userEvent.setup();

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    await user.clear(sqlBox());
    await waitFor(() => expect(saveButton()).toBeEnabled());
  });
});

describe("the preview", () => {
  /** What the pane last handed the widget to draw. */
  const drawnWith = () =>
    renderWidget.mock.calls.at(-1)?.[0] as
      | { slots?: Record<string, number[]>; data?: { rows?: unknown[] } }
      | undefined;

  it("tells the widget which columns fill its slots", async () => {
    // Without this every slot reads as unfilled, and a widget that draws
    // numbers reports it was handed none — whatever the statement returned.
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(drawnWith()?.data?.rows).toHaveLength(1));
    // `stat` takes a number and an optional label; the statement returns one
    // of each, in that order.
    expect(drawnWith()?.slots).toEqual({ value: [1], label: [0] });
  });

  it("honours a mapping the author corrected rather than inferring over it", async () => {
    mount({ ...widget({ source: "query", sql: SHIPPED_SQL }), mapping: { value: [0] } });

    await waitFor(() => expect(drawnWith()?.data?.rows).toHaveLength(1));
    expect(drawnWith()?.slots?.value).toEqual([0]);
  });
});

describe("what a new statement leaves out", () => {
  /** The catalog, answering with what the server derives for `tasks`. */
  const withDefaults = () =>
    server.use(
      http.get("/api/v1/fields/:dataset", ({ params }) =>
        HttpResponse.json({
          dataset: params.dataset,
          fields: [FIELD("title", "text"), FIELD("archived_at", "date")],
          relations: [{ name: "project", dataset: "projects" }],
          default_filters:
            params.dataset === "tasks"
              ? [
                  { field: "archived_at", op: "is_null", value: true },
                  { field: "project.is_template", op: "eq", value: false },
                ]
              : [],
        })
      )
    );

  it("starts a new widget without archived work or templates", async () => {
    withDefaults();
    mount(widget({ source: "query" }));

    await waitFor(() => {
      const where = described.build?.where as { field: string }[] | undefined;
      expect(where?.map((condition) => condition.field)).toEqual([
        "archived_at",
        "project.is_template",
      ]);
    });
  });

  it("shows them as filters rather than hiding them in the statement", async () => {
    // The whole point of seeding conditions instead of applying them server
    // side: an author can see what is being left out, and take it back.
    withDefaults();
    mount(widget({ source: "query" }));

    await screen.findByRole("tab", { name: /build/i });
    await waitFor(() => expect(screen.queryByText(/no filters/i)).not.toBeInTheDocument());
    // As a choice the author can change, not rows to read through.
    expect(await screen.findByRole("combobox", { name: /^archived$/i })).toHaveTextContent(
      /leave out/i
    );
  });

  it("leaves a statement somebody already wrote alone", async () => {
    // A stored statement opens on SQL and is never rewritten by being read.
    withDefaults();
    mount(widget({ source: "query", sql: SHIPPED_SQL }));

    await waitFor(() => expect(sqlBox()).toHaveValue(SHIPPED_SQL));
    expect(asked.build).toBe(0);
  });
});

describe("a target", () => {
  const saveButton = () => screen.getByRole("button", { name: /^save$/i });

  /** A stat whose catalog entry takes a target and its day. */
  const withTarget: WidgetCatalog = {
    widgets: [
      {
        type: "stat",
        min_w: 2,
        min_h: 2,
        default_w: 3,
        default_h: 2,
        shape: [],
        options: [
          { key: "target", values: [], default: "", kind: "number" },
          { key: "target_date", values: [], default: "", kind: "date" },
        ],
      },
    ],
    presets: [],
  };

  it("is typed rather than chosen, and left out once it is cleared", async () => {
    readWidgetMeta.mockResolvedValue({
      name: { en: "Stat" },
      options: {
        target: { label: { en: "Target" } },
        target_date: { label: { en: "Target date" } },
      },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <WidgetConfigDialog
        widget={widget({ source: "query", sql: SHIPPED_SQL })}
        catalog={withTarget}
        initiativeId={7}
        open
        onOpenChange={() => {}}
        onSave={onSave}
      />,
      { communities: { activeCommunityId: 2 } }
    );

    const target = await screen.findByLabelText("Target");
    await user.type(target, "50");
    await user.type(screen.getByLabelText("Target date"), "2026-06-30");
    await waitFor(() => expect(saveButton()).toBeEnabled());
    await user.click(saveButton());
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ options: { target: "50", target_date: "2026-06-30" } })
    );

    await user.clear(target);
    await user.clear(screen.getByLabelText("Target date"));
    await user.click(saveButton());
    expect(onSave.mock.lastCall?.[0].options).toBeUndefined();
  });
});

describe("reading a plug-in", () => {
  const ORDERS = { plugin: "acme.shop", endpoint: "orders" };

  beforeEach(() => {
    server.use(
      communityHttp.get("/plugins/widget-catalog", () =>
        HttpResponse.json({ items: [buildPluginCatalogEntry()] })
      )
    );
  });

  /** Chooses Plug-in data, which is offered once the catalog says a plug-in is
   *  installed. */
  const choosePluginData = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("combobox", { name: "Show data from" }));
    const option = await screen.findByRole("option", { name: "Plug-in data" });
    await waitFor(() => expect(option).not.toHaveAttribute("aria-disabled", "true"));
    await user.click(option);
  };

  it("is a statement, with no other source to choose", async () => {
    mount(widget({ source: "query" }));
    await screen.findByRole("tab", { name: /build/i });
    expect(screen.queryByRole("combobox", { name: /data source/i })).not.toBeInTheDocument();
  });

  it("is built from what was clicked, starting with every column it returns", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await choosePluginData(user);

    await waitFor(() => expect(described.build?.plugin).toEqual(ORDERS));
    await waitFor(() =>
      expect(described.build?.columns).toEqual([{ field: "status" }, { field: "total" }])
    );
    // Narrowed on its own columns, as a range is.
    await user.click(await screen.findByRole("button", { name: /add filter/i }));
    await waitFor(() => {
      const where = described.build?.where as { field: string }[] | undefined;
      expect(where?.[0]?.field).toBe("status");
    });
  });

  it("sends the endpoint's settings with it", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query" }));

    await choosePluginData(user);
    await user.type(await screen.findByLabelText("Range"), "30d");

    await waitFor(() =>
      expect(described.build?.plugin).toEqual({ ...ORDERS, params: { range: "30d" } })
    );
  });

  it("reopens on the plug-in it was built from", async () => {
    mount(
      widget({
        source: "query",
        sql: BUILT_SQL,
        spec: { plugin: ORDERS, columns: [{ field: "status" }], where: [], group_by: [] },
      })
    );

    // Named once the catalog says what is installed.
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Plug-in" })).toHaveTextContent("Shop")
    );
    expect(screen.getByRole("combobox", { name: "What it reads" })).toHaveTextContent("orders");
  });

  it("offers the installed plug-ins inside plugin('", async () => {
    const user = userEvent.setup();
    mount(widget({ source: "query", sql: "SELECT * FROM " }));

    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT * FROM "));
    await user.click(sqlBox());
    await user.type(sqlBox(), "plugin('");
    await user.click(await screen.findByRole("button", { name: /acme\.shop/i }));

    await waitFor(() => expect(sqlBox()).toHaveValue("SELECT * FROM plugin('acme.shop'"));
  });
});

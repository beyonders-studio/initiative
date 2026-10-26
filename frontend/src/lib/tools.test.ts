/**
 * Tool-registry drift tests — every per-tool surface must cover exactly what
 * the registry declares. A new tool (or a renamed key) fails here with a
 * message naming the missing surface, instead of silently shipping a tool
 * that's absent from the sidebar, palette, trash, recents, or i18n.
 *
 * Mirrors the backend's app/core/tools_test.py, which pins the same
 * derivations on the API side.
 */
import { describe, expect, it } from "vitest";

import {
  EntityType,
  PermissionKey,
  PropertyTarget,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TOOL_SKETCHES } from "@/components/initiatives/ToolSkeletons";
import { EXTRA_PERMISSION_KEYS } from "@/hooks/useInitiativeRoles";
import { PALETTE_TOOLS, TOOL_PALETTE } from "@/lib/toolPalette";
import { TOOL_HAS_DETAIL } from "@/lib/toolRows";
import {
  counterRoute,
  entityRefRoute,
  eventRoute,
  INITIATIVES_ROUTE,
  initiativeRoute,
  NO_RELATIONS_PANEL,
  NON_EXPORTABLE_TOOLS,
  PARENT_TOOL,
  SIDEBAR_TOOLS,
  showsRelations,
  singularOf,
  TOOL_ICONS,
  TOOL_SETTINGS_SECTIONS,
  TOOLS,
  taskRoute,
  toolCamelPlural,
  toolCamelSingular,
  toolCreateLabelKey,
  toolCreatePermission,
  toolDetailRoute,
  toolInPath,
  toolListRoute,
  toolNavLabelKey,
  toolParamName,
  toolPascalPlural,
  toolPlural,
  toolRouteSegment,
  toolSettingsRoute,
  toolSettingsSectionRoute,
  toolViewPermission,
} from "@/lib/tools";

import access from "../../public/locales/en/access.json";
import command from "../../public/locales/en/command.json";
import communityHome from "../../public/locales/en/communityHome.json";
import initiatives from "../../public/locales/en/initiatives.json";
import nav from "../../public/locales/en/nav.json";
import trash from "../../public/locales/en/trash.json";

// Route files (keys only — nothing is loaded). The community tree holds each
// tool's tab, detail, and settings routes, nested under their initiative.
const communityRouteFiles = Object.keys(
  import.meta.glob("../routes/_serverRequired/_authenticated/c/$communityId/**/*.tsx")
);
const INITIATIVE_ROUTES = "../routes/_serverRequired/_authenticated/c/$communityId/i/$initiativeId";
// Every page and component, as source text. Read rather than rendered: what
// is being asked is which tool a surface WIRES UP, and mounting nine detail
// pages to find out would cost more than the drift it catches.
// Item details draw their parts from lib/layouts.
const componentSources = import.meta.glob("../{pages,components,lib/layouts}/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const hookSources = import.meta.glob("../hooks/*.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Which tools something renders a `ToolRelationsPanel` for. */
const toolsWithRelationsPanel = (): Set<string> => {
  const found = new Set<string>();
  for (const source of Object.values(componentSources)) {
    for (const [, tool] of source.matchAll(/<ToolRelationsPanel[^>]*?tool=\{Tool\.(\w+)\}/gs)) {
      found.add(tool);
    }
    // An item's detail draws its links for the tool it is opened in.
    for (const [, tool] of source.matchAll(/canOpen: \{ tool: Tool\.(\w+)/g)) found.add(tool);
  }
  return found;
};

// Locale namespace files across every shipped language.
const localeFiles = Object.keys(import.meta.glob("../../public/locales/*/*.json"));
const locales = [...new Set(localeFiles.map((f) => f.split("/").at(-2)))];

describe("tool registry", () => {
  it("covers exactly the canonical Tool enum", () => {
    expect(Object.keys(TOOL_ICONS).sort()).toEqual(Object.values(Tool).sort());
    // And a sketch for the create wizard, for the same reason.
    expect(Object.keys(TOOL_SKETCHES).sort()).toEqual(Object.values(Tool).sort());
  });

  it("sidebar order is a permutation of the tools", () => {
    expect([...SIDEBAR_TOOLS].sort()).toEqual([...TOOLS].sort());
  });

  it("derives the exact permission keys the API exposes", () => {
    const derived = [
      ...TOOLS.flatMap((tool) => [toolViewPermission(tool), toolCreatePermission(tool)]),
      ...EXTRA_PERMISSION_KEYS,
    ];
    expect(derived.sort()).toEqual(Object.values(PermissionKey).sort());
  });

  it("every tool is a trash entity type with a label", () => {
    const trashTypes = Object.values(EntityType) as string[];
    const labels = trash.entityType as Record<string, string>;
    for (const tool of TOOLS) {
      expect(trashTypes, `missing EntityType for ${tool}`).toContain(tool);
    }
    for (const entityType of trashTypes) {
      expect(labels[entityType], `missing trash.json entityType.${entityType}`).toBeTruthy();
    }
  });
});

describe("tool i18n", () => {
  it("nav has a label and create label for every tool", () => {
    const keys: Record<string, unknown> = nav;
    for (const tool of TOOLS) {
      expect(keys[toolNavLabelKey(tool)], `missing nav.json ${toolNavLabelKey(tool)}`).toBeTruthy();
      expect(
        keys[toolCreateLabelKey(tool)],
        `missing nav.json ${toolCreateLabelKey(tool)}`
      ).toBeTruthy();
    }
  });

  it("every tool has its namespace file in every locale", () => {
    for (const locale of locales) {
      for (const tool of TOOLS) {
        const file = `../../public/locales/${locale}/${toolCamelPlural(tool)}.json`;
        expect(localeFiles, `missing ${file}`).toContain(file);
      }
    }
  });

  it("community home names every tool's own table column", () => {
    const detail = communityHome.columns.detail as Record<string, string>;
    for (const tool of TOOLS.filter((candidate) => TOOL_HAS_DETAIL[candidate])) {
      expect(
        detail[toolCamelPlural(tool)],
        `missing communityHome.json columns.detail.${toolCamelPlural(tool)}`
      ).toBeTruthy();
    }
  });

  it("command palette has a group label for every palette-enabled tool", () => {
    const groups = command.groups as Record<string, string>;
    for (const tool of PALETTE_TOOLS) {
      expect(
        groups[toolCamelPlural(tool)],
        `missing command.json groups.${toolCamelPlural(tool)}`
      ).toBeTruthy();
    }
  });

  it("bulk access bar has labels for every tool", () => {
    const bulkBar = access.bulkBar as Record<string, string>;
    for (const tool of TOOLS) {
      expect(
        bulkBar[`resource_${tool}_one`],
        `missing access.json bulkBar.resource_${tool}_one`
      ).toBeTruthy();
      expect(
        bulkBar[`resource_${tool}_other`],
        `missing access.json bulkBar.resource_${tool}_other`
      ).toBeTruthy();
    }
  });

  it("initiative settings i18n covers every tool", () => {
    const detail = initiatives.detail as Record<string, string>;
    const groups = initiatives.settings.permissionGroups as Record<string, string>;
    const permissions = initiatives.settings.permissions as Record<string, string>;
    for (const tool of TOOLS) {
      const camel = toolCamelPlural(tool);
      const pascalPlural = toolPascalPlural(tool);
      expect(detail[camel], `missing initiatives.json detail.${camel}`).toBeTruthy();
      expect(
        groups[camel],
        `missing initiatives.json settings.permissionGroups.${camel}`
      ).toBeTruthy();
      expect(
        permissions[`view${pascalPlural}`],
        `missing initiatives.json settings.permissions.view${pascalPlural}`
      ).toBeTruthy();
      expect(
        permissions[`create${pascalPlural}`],
        `missing initiatives.json settings.permissions.create${pascalPlural}`
      ).toBeTruthy();
    }
    const featureKeys = initiatives as unknown as Record<string, string>;
    for (const tool of TOOLS) {
      const camel = toolCamelPlural(tool);
      expect(
        featureKeys[`${camel}Feature`],
        `missing initiatives.json ${camel}Feature`
      ).toBeTruthy();
      expect(
        featureKeys[`${camel}FeatureDescription`],
        `missing initiatives.json ${camel}FeatureDescription`
      ).toBeTruthy();
    }
  });
});

describe("tool routes", () => {
  // A tool's list IS its initiative tab, so the route lives inside the
  // initiative tree. Six sibling files rather than one dynamic $toolSegment
  // route: a dynamic segment beside `settings`/`plugins` would resolve by
  // static-beats-dynamic ranking, which fails silently and only at runtime.
  it("every tool has its initiative tab route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/index.tsx`;
      expect(communityRouteFiles, `missing tab route file ${file}`).toContain(file);
    }
  });

  // Without this a tool could ship with a clickable card and nowhere to land.
  it("every tool has its per-entity detail route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/$${toolParamName(tool)}/index.tsx`;
      expect(communityRouteFiles, `missing detail route file ${file}`).toContain(file);
    }
  });

  // Every tool is renameable and deletable from its own settings page. The
  // absence of this check is how a tool shipped with no way to do either.
  it("every tool has its per-entity settings route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/$${toolParamName(tool)}/settings.tsx`;
      expect(communityRouteFiles, `missing settings route file ${file}`).toContain(file);
    }
  });

  // Every section of a tool's settings is an address, not component state.
  // A missing file is a tab that navigates to a blank page.
  it("every tool has a route per settings section", () => {
    for (const tool of TOOLS) {
      const settings = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/$${toolParamName(tool)}/settings`;
      for (const section of TOOL_SETTINGS_SECTIONS) {
        const file = section === "details" ? `${settings}/index.tsx` : `${settings}/${section}.tsx`;
        expect(communityRouteFiles, `missing settings section route file ${file}`).toContain(file);
      }
    }
  });

  // The tab routes are siblings of the initiative's own static children, so a
  // tool whose segment collided with one would be unreachable.
  it("no tool segment collides with a reserved initiative child route", () => {
    const reserved = new Set(["settings", "plugins"]);
    for (const tool of TOOLS) {
      expect(
        reserved.has(toolRouteSegment(tool)),
        `${tool} would shadow /i/$initiativeId/${toolRouteSegment(tool)}`
      ).toBe(false);
    }
  });

  it("pluralizes and singularizes by one rule, not by adding or chopping an s", () => {
    expect(toolPlural(Tool.catalog)).toBe("catalogs");
    expect(toolRouteSegment(Tool.catalog)).toBe("catalogs");
    expect(toolCamelPlural(Tool.catalog)).toBe("catalogs");
    expect(toolPascalPlural(Tool.catalog)).toBe("Catalogs");
    expect(singularOf("catalogs")).toBe("catalog");
    expect(singularOf("counter_groups")).toBe("counter_group");
    expect(singularOf("tasks")).toBe("task");
  });

  it("derives the route param name from the enum", () => {
    expect(toolCamelSingular(Tool.counter_group)).toBe("counterGroup");
    expect(toolParamName(Tool.counter_group)).toBe("counterGroupId");
    expect(toolParamName(Tool.project)).toBe("projectId");
  });
});

describe("tool route builders", () => {
  it("addresses a tool entity inside its initiative", () => {
    expect(toolListRoute(Tool.counter_group, 12)).toBe("/i/12/counter-groups");
    expect(toolDetailRoute(Tool.counter_group, 12, 3)).toBe("/i/12/counter-groups/3");
    expect(toolSettingsRoute(Tool.project, 1, 7)).toBe("/i/1/projects/7/settings");
  });

  // Details is the settings address itself, not a `/settings/details` alias.
  it("addresses each settings section", () => {
    expect(toolSettingsSectionRoute(Tool.project, 1, 7, "details")).toBe(
      "/i/1/projects/7/settings"
    );
    expect(toolSettingsSectionRoute(Tool.project, 1, 7, "access")).toBe(
      "/i/1/projects/7/settings/access"
    );
    expect(toolSettingsSectionRoute(Tool.calendar, null, 3, "advanced")).toBe(
      "/calendars/3/settings/advanced"
    );
  });

  // Only calendars have community-level entities (a plug-in installs one). A null
  // initiative means "address me at the community route", never "unknown".
  it("keeps a community-level entity at its community route", () => {
    expect(toolListRoute(Tool.calendar, null)).toBe("/calendars");
    expect(toolDetailRoute(Tool.calendar, null, 3)).toBe("/calendars/3");
    expect(toolSettingsRoute(Tool.calendar, null, 3)).toBe("/calendars/3/settings");
  });

  it("nests a child entity under its parent", () => {
    expect(taskRoute(1, 2, 5)).toBe("/i/1/projects/2/tasks/5");
    expect(eventRoute(1, 2, 9)).toBe("/i/1/calendars/2/events/9");
    expect(eventRoute(null, 2, 9)).toBe("/calendars/2/events/9");
    expect(counterRoute(1, 3, 7)).toBe("/i/1/counter-groups/3/counter/7");
  });

  it("names the initiative tree", () => {
    expect(INITIATIVES_ROUTE).toBe("/i");
    expect(initiativeRoute(4)).toBe("/i/4");
  });

  it("routes a bare id through the resolver", () => {
    expect(entityRefRoute("file", 42)).toBe("/go/file/42");
  });
});

describe("tool surfaces", () => {
  it("every tool has a command-palette source", () => {
    expect(Object.keys(TOOL_PALETTE).sort()).toEqual(Object.values(Tool).sort());
    expect(PALETTE_TOOLS).toEqual(TOOLS);
  });

  // Generous timeout: importing the page pulls in the whole tab-view graph,
  // which can take over 30s on a slow machine while the full suite's workers
  // are all transforming concurrently.
  it("every tool has an initiative-detail tab view", { timeout: 60_000 }, async () => {
    const { TOOL_TAB_VIEWS } = await import("@/pages/InitiativeDetailPage");
    for (const tool of TOOLS) {
      expect(
        TOOL_TAB_VIEWS.get(tool),
        `missing InitiativeDetailPage tab view for ${tool}`
      ).toBeTruthy();
    }
  });
});

describe("tool relations", () => {
  it("every tool shows what it is connected to, unless it says why not", () => {
    // Relations are a default surface, like a comment thread: a tool that does
    // not offer them has to be named in NO_RELATIONS_PANEL with its reason,
    // rather than simply never having been wired up.
    const wired = toolsWithRelationsPanel();
    const missing = TOOLS.filter((tool) => showsRelations(tool) && !wired.has(tool));
    expect(missing, `no ToolRelationsPanel wired for ${missing.join(", ")}`).toEqual([]);
  });

  it("does not wire a panel for a tool that opted out", () => {
    const wired = toolsWithRelationsPanel();
    for (const tool of NO_RELATIONS_PANEL) {
      expect(wired.has(tool), `${tool} opted out of relations but renders a panel`).toBe(false);
    }
  });

  it("names a parent tool for every entity that is not one", () => {
    // A link is cached against a tool, so a child entity has to say which one
    // answers for it — otherwise a write leaves the container's copy stale.
    expect(Object.values(PARENT_TOOL).every((tool) => TOOLS.includes(tool))).toBe(true);
    expect(Object.keys(PARENT_TOOL).sort()).toEqual([
      "calendar_event",
      "catalog_item",
      "counter",
      "queue_item",
      "task",
      "wiki_page",
    ]);
  });
});

describe("tool properties", () => {
  it("every tool and sub-tool has somewhere its properties are set", () => {
    const set = new Set<string>();
    for (const source of Object.values(componentSources)) {
      for (const [, target] of source.matchAll(/propertySaves\[PropertyTarget\.(\w+)\]/g)) {
        set.add(target);
      }
    }
    // An item's page saves them with the item's own save kind.
    for (const source of Object.values(hookSources)) {
      for (const [, target] of source.matchAll(/properties: PropertyTarget\.(\w+)/g)) {
        set.add(target);
      }
    }
    // A tool's are on its settings page, which every tool shares.
    if (
      componentSources["../pages/toolSettings/ToolSettingsDetailsPage.tsx"].includes(
        "propertySaves[PropertyTarget[tool]]"
      )
    ) {
      for (const tool of TOOLS) set.add(tool);
    }
    const missing = Object.values(PropertyTarget).filter((target) => !set.has(target));
    expect(missing, `nowhere sets the properties of ${missing.join(", ")}`).toEqual([]);
  });
});

describe("tool surfaces are wired, not just typed", () => {
  // Both of these shipped broken because the shape they fill is keyed by Tool
  // but every key was optional: the community home's table asked for posts, got a
  // response, and mapped it through a record that never mentioned them —
  // "No results", with nothing for the compiler to object to. The types are
  // required now; these pin the sources that fill them.

  it("the community-home row builder handles every tool", async () => {
    const { buildToolRows } = await import("@/lib/toolRows");
    const empty = Object.fromEntries(TOOLS.map((tool) => [tool, undefined])) as Parameters<
      typeof buildToolRows
    >[1];
    for (const tool of TOOLS) {
      // A tool missing its `case` falls out of the switch and returns
      // undefined, which is what an empty table looked like.
      expect(
        buildToolRows(tool, empty, ((key: string) => key) as never, 1),
        `buildToolRows has no case for ${tool}`
      ).toEqual([]);
    }
  });
});

describe("tool exports", () => {
  it("every bulk-export tool has a format source, and only those", async () => {
    const { FILE_TYPE_FORMATS, TOOL_EXPORT_FORMATS } = await import("@/components/exports/formats");
    const { FileType } = await import("@/api/generated/initiativeAPI.schemas");
    const { BULK_EXPORT_TOOLS } = await import("@/lib/tools");

    for (const tool of BULK_EXPORT_TOOLS) {
      // Files are per-type (their format set depends on the selection);
      // every file type must offer at least one engine format.
      if (tool === Tool.file) continue;
      expect(
        TOOL_EXPORT_FORMATS[tool]?.length,
        `missing TOOL_EXPORT_FORMATS[${tool}]`
      ).toBeGreaterThan(0);
    }
    for (const type of Object.values(FileType)) {
      expect(FILE_TYPE_FORMATS[type]?.length, `missing FILE_TYPE_FORMATS.${type}`).toBeGreaterThan(
        0
      );
    }
    // Exact coverage: a formats entry for a non-export tool is drift too.
    for (const tool of TOOLS) {
      if (NON_EXPORTABLE_TOOLS.has(tool) && tool !== Tool.file) {
        expect(
          TOOL_EXPORT_FORMATS[tool],
          `${tool} declares formats but is in NON_EXPORTABLE_TOOLS`
        ).toBeUndefined();
      }
    }
  });
});

describe("tool imports", () => {
  // Export and import are one capability — a tool's JSON envelope round-trips
  // through both — so they share BULK_EXPORT_TOOLS rather than two sets that
  // could drift apart.
  it("round-trips the envelope type discriminator for every portable tool", async () => {
    const { BULK_EXPORT_TOOLS, toolEnvelopeType, toolForEnvelopeType } = await import(
      "@/lib/tools"
    );
    for (const tool of BULK_EXPORT_TOOLS) {
      expect(toolForEnvelopeType(toolEnvelopeType(tool))).toBe(tool);
    }
    // Every type is the kebab-singular now; a backup type maps to no tool.
    expect(toolEnvelopeType(Tool.calendar)).toBe("initiative-calendar");
    expect(toolForEnvelopeType("initiative-backup")).toBeNull();
  });

  // The data-jobs table labels a job by its `source` column, which the backend
  // writes as the envelope type for an import and the adapter key for an
  // export. Both are derived from the enum, so both label sets are too — a key
  // that matches no source renders as its own raw key in the UI, which is how
  // `initiative-calendar-events` survived a calendar rename unnoticed.
  it("labels every import source in every locale", async () => {
    const { BULK_EXPORT_TOOLS, toolEnvelopeType } = await import("@/lib/tools");
    for (const locale of locales) {
      const file = await import(`../../public/locales/${locale}/imports.json`);
      const labels = (file.default ?? file).table.source as Record<string, string>;
      const expected = ["backup", ...BULK_EXPORT_TOOLS.map(toolEnvelopeType)];
      expect(Object.keys(labels).sort(), `${locale}/imports.json table.source`).toEqual(
        expected.sort()
      );
      for (const key of expected) {
        expect(labels[key], `${locale}/imports.json table.source.${key} is empty`).toBeTruthy();
      }
    }
  });

  it("labels every export source in every locale", async () => {
    const { BULK_EXPORT_TOOLS, toolKebabSingular } = await import("@/lib/tools");
    for (const locale of locales) {
      const file = await import(`../../public/locales/${locale}/exports.json`);
      const labels = (file.default ?? file).table.source as Record<string, string>;
      // `tasks` and `events` are the filterable task and event lists and
      // `initiative`/`community` are the aggregate backup scopes — the same
      // four non-tool sources the backend's adapter-coverage test allows.
      const expected = [
        "tasks",
        "events",
        "initiative",
        "community",
        ...BULK_EXPORT_TOOLS.map(toolKebabSingular),
      ];
      expect(Object.keys(labels).sort(), `${locale}/exports.json table.source`).toEqual(
        expected.sort()
      );
      for (const key of expected) {
        expect(labels[key], `${locale}/exports.json table.source.${key} is empty`).toBeTruthy();
      }
    }
  });
});

describe("toolInPath", () => {
  it("reads the tool and id a path is inside", () => {
    expect(toolInPath("/c/1/i/2/counter-groups/3")).toEqual({ tool: Tool.counter_group, id: 3 });
    expect(toolInPath("/c/1/calendars/5")).toEqual({ tool: Tool.calendar, id: 5 });
  });

  it("reads the outermost tool, so what it holds and its settings name it", () => {
    expect(toolInPath("/c/1/i/2/projects/3/tasks/5")).toEqual({ tool: Tool.project, id: 3 });
    expect(toolInPath("/c/1/i/2/wikis/4/files/8")).toEqual({ tool: Tool.wiki, id: 4 });
    expect(toolInPath("/c/1/i/2/queues/6/settings/access")).toEqual({ tool: Tool.queue, id: 6 });
  });

  it("is null anywhere that is no tool's page", () => {
    expect(toolInPath("/c/1/i/2/projects")).toBeNull();
    expect(toolInPath("/c/1/i/2/dashboards/gallery")).toBeNull();
    expect(toolInPath("/c/1/settings/users")).toBeNull();
    expect(toolInPath("/c/1/go/file/42")).toBeNull();
  });
});

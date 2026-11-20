import {
  ActorKind,
  type CommunityPluginRead,
  type PluginToolRowRead,
} from "@/api/generated/initiativeAPI.schemas";
import { type ToolRow, toolRow } from "@/lib/toolPlugins";

import { writerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** The uid of the tool plug-in `buildToolPlugin` installs. */
export const TOOL_PLUGIN_UID = "SHELF000000001";

const field = (key: string) => ({ type: "field", props: { field: key } });

/**
 * A tool plug-in's definition: a reading shelf, whose books sit under it and
 * count the pages read toward each book's length.
 */
export const shelfDefinition = () => ({
  plugin_kind: "tool",
  features: ["tool"],
  default_name: "Reading",
  tool: {
    key: "shelf",
    name: { en: "Reading", de: "Lesen" },
    instance_name: { en: "Shelf", de: "Regal" },
    icon: "book",
    fields: [{ key: "about", name: { en: "About" }, kind: "text" }],
    layouts: {
      lists: [
        {
          kind: "grid",
          card: { type: "card", children: [field("name"), field("about")] },
          presets: [
            { slug: "a_z", name: { en: "A to Z" }, sort: [{ field: "name", dir: "asc" }] },
            { slug: "z_a", name: { en: "Z to A" }, sort: [{ field: "name", dir: "desc" }] },
          ],
        },
        { kind: "table", columns: ["name", "about"] },
      ],
      detail: {
        header: [
          {
            type: "stack",
            props: { direction: "row", gap: "sm", align: "start" },
            children: [field("name"), { type: "actions" }],
          },
        ],
        main: [field("about"), { type: "relations" }],
        side: [{ type: "byline" }],
      },
    },
    items: [
      {
        key: "book",
        name: { en: "Book", de: "Buch" },
        fields: [
          { key: "pages", name: { en: "Pages" }, kind: "number" },
          {
            key: "read",
            name: { en: "Read", de: "Gelesen" },
            kind: "counter",
            counter: { min: 0, max: "pages" },
          },
          { key: "cover", name: { en: "Cover" }, kind: "color" },
          {
            key: "status",
            name: { en: "Status" },
            kind: "select",
            options: [
              { value: "unread", label: { en: "Unread", de: "Ungelesen" } },
              { value: "done", label: { en: "Read", de: "Gelesen" } },
            ],
          },
        ],
        layouts: {
          lists: [
            {
              kind: "grid",
              card: {
                type: "card",
                props: { tint: "cover" },
                children: [field("name"), field("read")],
              },
              displays: { read: "bar" },
            },
          ],
          detail: {
            header: [field("name")],
            main: [field("read"), { type: "comments" }],
            side: [
              {
                type: "section",
                children: [field("pages"), field("cover"), field("status")],
              },
              { type: "notice" },
            ],
          },
        },
      },
    ],
  },
});

/** An install of a tool plug-in, the reading shelf unless `definition` says
 *  otherwise. */
export function buildToolPlugin(
  overrides: Partial<CommunityPluginRead> = {}
): CommunityPluginRead & { definition: Record<string, unknown> } {
  counter++;
  return {
    id: counter,
    community_id: 1,
    listing_uid: TOOL_PLUGIN_UID,
    listing_version: "1.0.0",
    plugin_kind: "tool",
    name: "Reading",
    enabled: true,
    auto_update: true,
    pending_version: null,
    artifacts: [],
    needs_config: false,
    config_state: "ready",
    config_state_detail: null,
    tool: null,
    avatar_url: null,
    features: ["tool"],
    definition: shelfDefinition(),
    placed_initiative_ids: [],
    permissions: [],
    surface_access: [],
    item_access: [],
    setting_values: {},
    granted_scopes: [],
    mandatory: false,
    available: true,
    read_only: false,
    created_by: 1,
    created_at: "2026-11-01T00:00:00.000Z",
    updated_at: "2026-11-01T00:00:00.000Z",
    ...overrides,
  } as CommunityPluginRead & { definition: Record<string, unknown> };
}

/** A row of a tool plug-in's table, as the generic routes read it. */
export function buildToolRowRead(overrides: Partial<PluginToolRowRead> = {}): PluginToolRowRead {
  counter++;
  return {
    kind: `book.${TOOL_PLUGIN_UID.toLowerCase()}`,
    id: counter,
    community_id: 1,
    initiative_id: 1,
    parent_id: null,
    name: `Row ${counter}`,
    position: counter,
    fields: {},
    people: {},
    created_by: 1,
    created_by_kind: ActorKind.member,
    created_by_install: null,
    archived_at: null,
    can: writerCan(),
    comments_enabled: true,
    grants: [],
    created_at: "2026-11-01T00:00:00.000Z",
    updated_at: "2026-11-02T00:00:00.000Z",
    ...overrides,
  };
}

/** A row of a tool plug-in's table, as the kit draws it. */
export const buildToolRow = (overrides: Partial<PluginToolRowRead> = {}): ToolRow =>
  toolRow(buildToolRowRead(overrides));

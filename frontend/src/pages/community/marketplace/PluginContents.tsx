/**
 * What a plug-in is, for someone deciding whether to add it.
 *
 * The tag gives the rough idea on a card and at the top of a listing: how the
 * plug-in shows up for the people using it. The table under the description
 * says exactly what it adds, by name, read off the definition the listing
 * would install, so no publisher writes it and none can leave it out.
 */

import { AppWindow, ChevronRight, Plug, Puzzle, Users, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PluginTag } from "@/api/generated/initiativeAPI.schemas";
import { declaredPages } from "@/lib/pluginSurfaces";
import { kindNames } from "@/lib/tools";
import { localized } from "@/lib/widgets/widgetMeta";
import { Badge } from "@/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { listFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";

const TAG_ICONS = {
  [PluginTag.tool]: Wrench,
  [PluginTag.community_tool]: Users,
  [PluginTag.page]: AppWindow,
  [PluginTag.connection]: Plug,
  [PluginTag.add_on]: Puzzle,
} satisfies Record<PluginTag, unknown>;

export function PluginTagBadge({ tag, className }: { tag?: PluginTag | null; className?: string }) {
  const { t } = useTranslation("marketplace");
  if (!tag) return null;
  const Icon = TAG_ICONS[tag];
  return (
    <Badge variant="outline" className={cn("gap-1", className)}>
      <Icon className="size-3.5" aria-hidden />
      {t(`tag.${tag}`)}
    </Badge>
  );
}

type Entry = Record<string, unknown>;

const entries = (definition: Entry, block: string): Entry[] => {
  const value = definition[block];
  return Array.isArray(value)
    ? value.filter((item): item is Entry => typeof item === "object" && item !== null)
    : [];
};

/** A manifest name: one string, or one per language. */
const nameOf = (raw: unknown, language: string, fallback: unknown): string => {
  if (typeof raw === "string" && raw) return raw;
  if (typeof raw === "object" && raw !== null) {
    const picked = localized(raw as Record<string, string>, language);
    if (picked) return picked;
  }
  return typeof fallback === "string" ? fallback : "";
};

export function PluginContents({ definition }: { definition: Entry }) {
  const { t, i18n } = useTranslation(["marketplace", "common"]);
  const [open, setOpen] = useState(false);
  const language = i18n.language;
  const kindsOf = (kind: string) => kindNames(kind, t as (key: string) => string);
  const list = (names: string[]) => listFormat(language, { type: "conjunction" }).format(names);
  const names = (block: string, key = "name", fallback = "id") =>
    entries(definition, block)
      .map((entry) => nameOf(entry[key], language, entry[fallback]))
      .filter(Boolean);
  // What the items a block lands on are called: "on tasks", "on tasks and events".
  const on = (block: string) => {
    const kinds = [
      ...new Set(
        entries(definition, block).flatMap((entry) =>
          Array.isArray(entry.on) ? (entry.on as string[]) : []
        )
      ),
    ];
    return kinds.length
      ? t("contents.on", {
          kinds: list(kinds.map((kind) => kindsOf(kind).kinds)),
        })
      : null;
  };

  const rows: { label: string; value: ReactNode; note?: string | null }[] = [];

  if (definition.plugin_kind === "tool") {
    const tool = (definition.tool ?? {}) as Entry;
    rows.push({
      label: t("contents.tool"),
      value: t("contents.toolInitiatives", { name: nameOf(tool.name, language, tool.key) }),
    });
  } else if (definition.plugin_kind === "tool_instance" && typeof definition.tool === "string") {
    rows.push({
      label: t("contents.tool"),
      value: t("contents.toolCommunity", {
        name: kindsOf(definition.tool).kind,
      }),
    });
  }

  const community = declaredPages(definition, "community");
  const initiative = declaredPages(definition, "initiative");
  const pages = [...new Set([...community, ...initiative])];
  if (pages.length) {
    rows.push({
      label: t("contents.pages"),
      value: list(pages.map((page) => nameOf(page.name, language, page.id))),
      note:
        community.length && initiative.length
          ? t("contents.pagesBoth")
          : initiative.length
            ? t("contents.pagesInitiatives")
            : t("contents.pagesCommunity"),
    });
  }

  const dashboards = names("dashboards", "name", "public_id");
  if (dashboards.length) rows.push({ label: t("contents.dashboards"), value: list(dashboards) });

  const widgets = entries(definition, "widgets")
    .map((widget) => nameOf((widget.meta as Entry | undefined)?.name, language, widget.id))
    .filter(Boolean);
  if (widgets.length) {
    rows.push({
      label: t("contents.widgets"),
      value: list(widgets),
      note: t("contents.widgetsNote"),
    });
  }

  for (const [block, label] of [
    ["fields", t("contents.fields")],
    ["parts", t("contents.parts")],
    ["actions", t("contents.actions")],
  ] as const) {
    const found = names(block, "name", block === "fields" ? "key" : "id");
    if (found.length) rows.push({ label, value: list(found), note: on(block) });
  }

  const connections = entries(definition, "connections");
  if (connections.length) {
    rows.push({
      label: t("contents.connections"),
      value: (
        <ul className="space-y-0.5">
          {connections.map((connection) => (
            <li key={String(connection.id)}>
              {nameOf(connection.label, language, connection.id)}
              <span className="text-muted-foreground">
                {" · "}
                {connection.scope === "interactive"
                  ? t("contents.connectionMember")
                  : t("contents.connectionCommunity")}
              </span>
            </li>
          ))}
        </ul>
      ),
    });
  }

  if (!rows.length) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="space-y-2">
      <CollapsibleTrigger className="flex items-center gap-1 font-medium text-sm">
        <ChevronRight
          className={cn("size-4 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        {t("contents.title")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <table className="w-full max-w-2xl text-sm">
          <tbody className="divide-y">
            {rows.map((row) => (
              <tr key={row.label} className="align-top">
                <th
                  scope="row"
                  className="w-36 py-2 pr-4 text-left font-normal text-muted-foreground"
                >
                  {row.label}
                </th>
                <td className="py-2">
                  {row.value}
                  {row.note && <span className="text-muted-foreground"> · {row.note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CollapsibleContent>
    </Collapsible>
  );
}

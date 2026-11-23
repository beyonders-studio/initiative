/**
 * What a plug-in is, for someone deciding whether to add it.
 *
 * The tag gives the rough idea on a card and at the top of a listing: how the
 * plug-in shows up for the people using it. The table under the description
 * says exactly what it adds, by name, read off the definition the listing
 * would install, so no publisher writes it and none can leave it out.
 */

import { AppWindow, ChevronRight, Plug, Puzzle, Users, Wrench } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PluginTag } from "@/api/generated/initiativeAPI.schemas";
import { declaredPages } from "@/lib/pluginSurfaces";
import { kindNames } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { listFormat } from "@/ui/lib/intl";
import { localized } from "@/ui/lib/localized";
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

/** One line of a row: names sharing a location, and that location. */
type Line = { text: string; note?: string | null };

export function PluginContents({ definition }: { definition: Entry }) {
  const { t, i18n } = useTranslation(["marketplace", "common"]);
  const [open, setOpen] = useState(false);
  const language = i18n.language;
  const kindsOf = (kind: string) => kindNames(kind, t as (key: string) => string);
  const list = (names: string[]) => listFormat(language, { type: "conjunction" }).format(names);
  // Names that land in the same place share a line, so each line says where
  // its own names are.
  const grouped = (items: { name: string; note?: string | null }[]): Line[] => {
    const byNote = new Map<string, string[]>();
    for (const item of items) {
      if (!item.name) continue;
      const key = item.note ?? "";
      byNote.set(key, [...(byNote.get(key) ?? []), item.name]);
    }
    return [...byNote].map(([note, names]) => ({ text: list(names), note: note || null }));
  };
  // What the items an entry lands on are called: "on tasks", "on tasks and events".
  const on = (entry: Entry) =>
    Array.isArray(entry.on) && entry.on.length
      ? t("contents.on", {
          kinds: list((entry.on as string[]).map((kind) => kindsOf(kind).kinds)),
        })
      : null;

  const rows: { label: string; lines: Line[] }[] = [];
  const add = (label: string, lines: Line[]) => {
    if (lines.length) rows.push({ label, lines });
  };

  if (definition.plugin_kind === "tool") {
    const tool = (definition.tool ?? {}) as Entry;
    add(t("contents.tool"), [
      { text: t("contents.toolInitiatives", { name: nameOf(tool.name, language, tool.key) }) },
    ]);
  } else if (definition.plugin_kind === "tool_instance" && typeof definition.tool === "string") {
    add(t("contents.tool"), [
      { text: t("contents.toolCommunity", { name: kindsOf(definition.tool).kind }) },
    ]);
  }

  const community = declaredPages(definition, "community");
  const initiative = declaredPages(definition, "initiative");
  add(
    t("contents.pages"),
    grouped(
      [...new Set([...community, ...initiative])].map((page) => ({
        name: nameOf(page.name, language, page.id),
        note:
          community.includes(page) && initiative.includes(page)
            ? t("contents.pagesBoth")
            : initiative.includes(page)
              ? t("contents.pagesInitiatives")
              : t("contents.pagesCommunity"),
      }))
    )
  );

  add(
    t("contents.dashboards"),
    grouped(
      entries(definition, "dashboards").map((dashboard) => ({
        name: nameOf(dashboard.name, language, dashboard.public_id),
      }))
    )
  );

  add(
    t("contents.widgets"),
    grouped(
      entries(definition, "widgets").map((widget) => ({
        name: nameOf((widget.meta as Entry | undefined)?.name, language, widget.id),
        note: t("contents.widgetsNote"),
      }))
    )
  );

  for (const [block, label] of [
    ["fields", t("contents.fields")],
    ["parts", t("contents.parts")],
    ["actions", t("contents.actions")],
  ] as const) {
    add(
      label,
      grouped(
        entries(definition, block).map((entry) => ({
          name: nameOf(entry.name, language, block === "fields" ? entry.key : entry.id),
          note: on(entry),
        }))
      )
    );
  }

  add(
    t("contents.connections"),
    entries(definition, "connections").map((connection) => ({
      text: nameOf(connection.label, language, connection.id),
      note:
        connection.scope === "interactive"
          ? t("contents.connectionMember")
          : t("contents.connectionCommunity"),
    }))
  );

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
                <td className="space-y-0.5 py-2">
                  {row.lines.map((line) => (
                    <p key={`${line.text}${line.note ?? ""}`}>
                      {line.text}
                      {line.note && <span className="text-muted-foreground"> · {line.note}</span>}
                    </p>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CollapsibleContent>
    </Collapsible>
  );
}

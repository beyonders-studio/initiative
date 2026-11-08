/**
 * What's recent, from every community, two ways — switched from the title row:
 *
 * - **Viewed**: what the reader opened lately, the tabs along the top of the
 *   app as a list. The way back to whatever they were in the middle of.
 * - **Changed**: one kind of tool, freshest first — the top of My Tools'
 *   table for it, in the same order, so the title opens the rest.
 *
 * Both cover every kind of tool unless the reader picks some in its settings,
 * which narrows either list to those.
 */

import { Link } from "@tanstack/react-router";
import { History, PencilLine } from "lucide-react";
import { createElement, type ReactNode, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { useCommunities } from "@/hooks/useCommunities";
import { useRecentlyChangedTools } from "@/hooks/useMyTools";
import { useRecents } from "@/hooks/usePersonalItems";
import { communityPath } from "@/lib/communityUrl";
import { renderRecentIcon } from "@/lib/recentIcon";
import { recentRoute } from "@/lib/recentRoute";
import { TOOL_ICONS, toolNavLabelKey, toolRouteSegment } from "@/lib/tools";
import { Button } from "@/ui/button";
import { RelativeTime } from "@/ui/relative-time";
import { Skeleton } from "@/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

import { ToolsSetting, toolsOf } from "./toolFilter";
import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

type Mode = "viewed" | "changed";

const CHANGED_ROWS = 8;

const modeOf = (options: Record<string, unknown>): Mode =>
  options.mode === "changed" ? "changed" : "viewed";

/** One line of either list: what it is, where, and when. */
interface Row {
  key: string;
  to: string;
  icon: ReactNode;
  name: string;
  detail: string;
  at: string;
}

export const RecentWidget = ({ options, onOptionsChange }: HomeWidgetProps) => {
  const { t } = useTranslation("home");
  const { t: tNav } = useTranslation("nav");
  const mode = modeOf(options);
  const tools = toolsOf(options);
  // One kind has a full list of its own on My Tools for the title to open.
  const only = tools.length === 1 ? tools[0] : null;

  return (
    <HomeWidgetCard
      icon={mode === "changed" ? PencilLine : History}
      title={
        only
          ? t(mode === "changed" ? "widgets.recent.changedIn" : "widgets.recent.viewedIn", {
              tool: tNav(toolNavLabelKey(only)),
            })
          : t(mode === "changed" ? "widgets.recent.changed" : "widgets.recent.viewed")
      }
      to={mode === "changed" ? "/my-tools" : undefined}
      search={
        mode === "changed" && only
          ? { tool: toolRouteSegment(only), sort: "updated_at", dir: "desc" }
          : undefined
      }
      actions={
        <ToggleGroup
          type="single"
          size="sm"
          value={mode}
          onValueChange={(next) => {
            if (next) onOptionsChange({ ...options, mode: next });
          }}
          aria-label={t("widgets.recent.mode")}
        >
          <ToggleGroupItem value="viewed" aria-label={t("widgets.recent.viewed")}>
            <History className="size-4" />
          </ToggleGroupItem>
          <ToggleGroupItem value="changed" aria-label={t("widgets.recent.changed")}>
            <PencilLine className="size-4" />
          </ToggleGroupItem>
        </ToggleGroup>
      }
    >
      {mode === "changed" ? <ChangedList tools={tools} /> : <ViewedList tools={tools} />}
    </HomeWidgetCard>
  );
};

function ViewedList({ tools }: { tools: Tool[] }) {
  const { t } = useTranslation(["home", "search"]);
  const recents = useRecents();
  const where = useCommunityLabel();

  const rows = useMemo<Row[]>(
    () =>
      (recents.data ?? [])
        .filter((item) => tools.includes(item.entity_type as Tool))
        .map((item) => {
          const kind = t(`search:types.${item.entity_type}` as never, {
            defaultValue: item.entity_type,
          });
          const place = where(item.community_id);
          return {
            key: `${item.community_id}:${item.entity_type}:${item.entity_id}`,
            to: recentRoute(item),
            icon: renderRecentIcon(item),
            name: item.name,
            detail: place ? `${kind} · ${place}` : kind,
            // A tab is an open, so it always has one.
            at: item.viewed_at ?? "",
          };
        }),
    [recents.data, tools, t, where]
  );

  return (
    <RowList
      rows={rows}
      isLoading={recents.isLoading}
      isError={recents.isError}
      empty={t("widgets.recent.emptyViewed")}
    />
  );
}

function ChangedList({ tools }: { tools: Tool[] }) {
  const { t } = useTranslation(["home", "search"]);
  const changed = useRecentlyChangedTools(tools, CHANGED_ROWS);
  const where = useCommunityLabel();
  const several = tools.length > 1;

  const rows = useMemo<Row[]>(
    () =>
      changed.rows.map(({ tool, row }) => {
        const kind = several ? t(`search:types.${tool}` as never, { defaultValue: tool }) : null;
        const place = where(row.communityId);
        return {
          key: `${tool}:${row.communityId}:${row.id}`,
          to: communityPath(row.communityId, row.href),
          icon:
            row.glyph ??
            createElement(TOOL_ICONS[tool], { className: "size-4 text-muted-foreground" }),
          name: row.name,
          detail: [kind, place].filter(Boolean).join(" · "),
          at: row.updatedAt,
        };
      }),
    [changed.rows, several, t, where]
  );

  return (
    <RowList
      rows={rows}
      isLoading={changed.isLoading}
      isError={changed.isError}
      empty={t("widgets.recent.emptyChanged")}
    />
  );
}

/** A row's community, said only to somebody who is in more than one. */
const useCommunityLabel = () => {
  const { communities } = useCommunities();
  return useMemo(() => {
    const names = new Map(communities.map((community) => [community.id, community.name]));
    const several = communities.length > 1;
    return (communityId: number) => (several ? (names.get(communityId) ?? null) : null);
  }, [communities]);
};

function RowList({
  rows,
  isLoading,
  isError,
  empty,
}: {
  rows: Row[];
  isLoading: boolean;
  isError: boolean;
  empty: string;
}) {
  const { t } = useTranslation("home");
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
          <Skeleton key={i} className="h-10 rounded-lg" />
        ))}
      </div>
    );
  }
  if (isError) return <p className="text-destructive text-sm">{t("widgets.recent.loadError")}</p>;
  if (rows.length === 0) {
    return (
      <HomeWidgetNotice
        icon={History}
        action={
          <Button asChild size="sm" variant="outline">
            <Link to="/my-tools">{t("widgets.recent.openTools")}</Link>
          </Button>
        }
      >
        {empty}
      </HomeWidgetNotice>
    );
  }
  return (
    <ul className="space-y-1">
      {rows.map((row) => (
        <li key={row.key}>
          <Link
            to={row.to}
            className="flex items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-accent"
          >
            <span className="flex size-6 shrink-0 items-center justify-center">{row.icon}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-sm">{row.name}</span>
              {row.detail ? (
                <span className="block truncate text-muted-foreground text-xs">{row.detail}</span>
              ) : null}
            </span>
            <RelativeTime date={row.at} className="shrink-0 text-muted-foreground text-xs" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export const RecentSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  return (
    <ToolsSetting
      id="recent-widget-tools"
      options={options}
      onChange={onChange}
      hint={t("widgets.recent.toolsHint")}
    />
  );
};

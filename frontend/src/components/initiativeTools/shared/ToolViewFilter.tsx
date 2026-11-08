/**
 * Which view of a tool's list is showing — live, templates, or archived.
 *
 * Every tool can be archived, so every tool list needs somewhere for the
 * archived ones to be: a row that vanishes from its list with no way to reach
 * it is a row nobody can take back out. The views are states of one list
 * rather than separate destinations, so this sits beside the list instead of
 * being a second row of tabs, and every view stays visible with its total, so
 * a view advertises itself instead of hiding behind a menu. Which views a tool
 * has comes from the tool registry (`toolViews`).
 *
 * Lives in {@link ToolListToolbar}'s `leading` slot — the scope the list is
 * showing — beside the filter and view controls rather than inside the filter
 * panel, because it changes what the list *is* rather than narrowing it.
 *
 * An export asks a third thing — live and archived both — so it offers "All"
 * as well, and that is the export's default.
 */

import { Archive, Layers, LayoutTemplate } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_ICONS, type ToolView, toolViews } from "@/lib/tools";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** What an export takes: either archive state, or both ("all"). */
export type ToolArchiveChoice = "all" | "active" | "archived";

const EXPORT_CHOICES: readonly ToolArchiveChoice[] = ["all", "active", "archived"];

type ToolViewFilterProps =
  | {
      tool: Tool;
      includeAll?: false;
      value: ToolView;
      onChange: (value: ToolView) => void;
      /** Rows in each view; a view whose count hasn't loaded shows no badge. */
      counts?: Partial<Record<ToolView, number | undefined>>;
    }
  | {
      tool: Tool;
      includeAll: true;
      value: ToolArchiveChoice;
      onChange: (value: ToolArchiveChoice) => void;
      counts?: never;
    };

export const ToolViewFilter = ({
  tool,
  includeAll,
  value,
  onChange,
  counts,
}: ToolViewFilterProps) => {
  const { t } = useTranslation("common");

  // Templates deliberately avoid file iconography — that belongs to the
  // files tool.
  const icons = {
    all: Layers,
    active: TOOL_ICONS[tool],
    templates: LayoutTemplate,
    archived: Archive,
  } as const;
  const views: readonly (ToolView | "all")[] = includeAll ? EXPORT_CHOICES : toolViews(tool);

  return (
    <ToggleGroup
      type="single"
      value={value}
      // Radix clears a single-select group when the active item is clicked
      // again; the list is always showing one of its views.
      onValueChange={(next) =>
        next && (onChange as (value: ToolView | "all") => void)(next as ToolView | "all")
      }
      aria-label={t("toolViewFilter.label")}
      className="h-9 shrink-0 justify-start"
    >
      {views.map((view) => {
        const Icon = icons[view];
        const count = view === "all" ? undefined : counts?.[view];
        return (
          <ToggleGroupItem
            key={view}
            value={view}
            // Below `sm` the label drops and the icon carries it — the views
            // plus their totals share the row with the filter, view, and
            // overflow controls. `shrink-0` because a squeezed toggle clips
            // its own label and count rather than eliding them.
            aria-label={t(`toolViewFilter.${view}` as const)}
            className="h-9 shrink-0 gap-1.5 px-2.5 sm:gap-2 sm:px-3"
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{t(`toolViewFilter.${view}` as const)}</span>
            {typeof count === "number" ? (
              <span className="text-muted-foreground text-xs tabular-nums">{count}</span>
            ) : null}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
};

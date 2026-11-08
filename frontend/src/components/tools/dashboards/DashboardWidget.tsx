/**
 * One placed widget: its data, its chrome, and its authoring affordances.
 *
 * Sits between the canvas (which owns position) and `WidgetTile` (which owns
 * running the widget and drawing its scene). Everything visible here is plug-in
 * code — the drag handle, the menu, the unbound state — because a widget draws
 * only inside its box and must never be able to render something that looks
 * like the frame around it.
 */

import {
  BarChart3,
  EyeOff,
  GripVertical,
  MoreVertical,
  Settings2,
  Table2,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { pluginWidgetSample, pluginWidgetSource } from "@/api/pluginData";
import { WidgetProvenance } from "@/components/tools/dashboards/WidgetProvenance";
import { WidgetTile } from "@/components/tools/dashboards/WidgetTile";
import { useWidgetCatalog } from "@/hooks/useDashboards";
import { usePluginWidgetCatalog } from "@/hooks/usePluginData";
import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { type DefinitionWidget, isPluginWidgetType, unboundSlots } from "@/lib/widgets/definition";
import { SAMPLE_NOW, sampleFor } from "@/lib/widgets/sampleData";
import { canDraw, resolveMapping } from "@/lib/widgets/shape";
import { shapeFor } from "@/lib/widgets/shapes";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

export interface DashboardWidgetProps {
  widget: DefinitionWidget;
  binding: WidgetBinding;
  /** The dashboard's own initiative — the only one its widgets read from. */
  initiativeId: number | undefined;
  /** The dashboard row itself. Only the `plugin` source needs it: its data is
   *  community-level, so the proxy is told which initiative-scoped surface is
   *  asking and decides against that row's gates. */
  dashboardId?: number;
  canEdit: boolean;
  /** Draw the sample library instead of resolving the binding — nothing is
   *  fetched at all. This is the marketplace preview's mode: a listing that
   *  isn't installed shows what it *looks like*, never anyone's data, so it
   *  renders the same for every viewer. */
  sampleData?: boolean;
  onConfigure?: (widgetId: string) => void;
  onRemove?: (widgetId: string) => void;
}

export function DashboardWidget({
  widget,
  binding,
  initiativeId,
  dashboardId,
  canEdit,
  sampleData,
  onConfigure,
  onRemove,
}: DashboardWidgetProps) {
  const { t } = useTranslation("dashboards");
  const isPluginWidget = isPluginWidgetType(widget.type);

  // A plug-in widget's module lives in the install's pinned definition rather than
  // in this build's registry — the seam `WidgetTile.source` exists for. The
  // catalog is one shared query per community, so a canvas full of plug-in widgets
  // resolves them all from one request.
  //
  // In sample mode it is fetched too, and only then: a preview draws the plug-in's
  // *own* sample rows through the plug-in's own module, so what it shows is the
  // listing rather than a stand-in. It still issues no data request — no
  // initiative, no dashboard, nothing to fetch.
  const pluginCatalogQuery = usePluginWidgetCatalog(isPluginWidget);
  const moduleSource = isPluginWidget
    ? pluginWidgetSource(pluginCatalogQuery.data, widget.type)
    : undefined;

  // Named from its own module, like every widget: a plug-in names its widgets in
  // the manifest, so a marketplace tile has a real title without a locale edit
  // here. Falls back to the type id until the sandbox read resolves.
  const { name, meta } = useWidgetMeta(widget.type, moduleSource);

  // In sample mode the hook still runs (hooks are unconditional) but is handed
  // no initiative, which fail-closes every query — a preview issues no
  // requests, exactly like the widget picker's.
  const live = useWidgetData(
    binding,
    sampleData ? undefined : initiativeId,
    sampleData ? undefined : dashboardId,
    widget.id
  );

  const [view, setView] = useState<"scene" | "table">("scene");

  const pluginSample = pluginWidgetSample(
    pluginCatalogQuery.data,
    widget.type,
    binding.endpoint_id
  );
  const data = sampleData
    ? isPluginWidget
      ? { source: "plugin" as const, ...pluginSample }
      : sampleFor(widget.type)
    : live.data;
  // Which columns fill this widget's slots. Resolved here rather than in the
  // sandbox: it needs the widget's declared shape and the author's overrides,
  // and neither is the widget's to read.
  const catalogQuery = useWidgetCatalog();
  const shape = shapeFor(widget.type, catalogQuery.data);
  const rows = data.source === "rows";
  // The author's overrides name columns of their own query, so sample rows are
  // matched to the slots afresh.
  const mapping = sampleData ? undefined : widget.mapping;
  const slots = rows ? resolveMapping(data.columns, shape, mapping) : undefined;
  // A query edited under a saved widget can stop returning the shape it draws.
  // The table draws any shape, so it is what a tile falls back to — showing the
  // rows that did come back beats showing an empty chart.
  const drawable = !rows || canDraw(data.columns, shape, mapping);
  const isLoading = sampleData ? false : live.isLoading;
  const errorCode = sampleData ? undefined : live.errorCode;

  const title = widget.title || name;
  // Three states that used to be one. "Nothing chosen yet" asks the author to
  // finish the job; "you can't see this" is not addressed to them at all, and
  // showing them a Configure button would invite repointing a binding that was
  // never wrong.
  const unconfigured = !sampleData && live.isUnbound && unboundSlots(binding).length > 0;
  const restricted = !sampleData && live.isRestricted;

  return (
    <section
      className="group/widget flex h-full w-full flex-col overflow-hidden rounded-lg border bg-card text-card-foreground"
      aria-label={title}
    >
      <header
        className={cn(
          "flex shrink-0 items-start gap-1 border-b px-2 py-1.5",
          canEdit && "cursor-grab active:cursor-grabbing"
        )}
        // The whole header is the drag handle, so a widget's own content never
        // becomes one — RGL is told to grab only on this attribute.
        {...(canEdit ? { "data-widget-handle": true } : {})}
      >
        {canEdit && (
          <GripVertical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold text-sm">{title}</h3>
          {!sampleData && (
            <WidgetProvenance
              binding={binding}
              meta={live.meta}
              options={widget.options}
              widgetMeta={meta}
              onRefresh={live.refetch}
            />
          )}
        </div>
        {!unconfigured && !restricted && drawable && (
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 shrink-0 opacity-0 focus-visible:opacity-100 group-hover/widget:opacity-100"
            aria-label={t(view === "scene" ? "canvas.tableView" : "canvas.chartView")}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => setView(view === "scene" ? "table" : "scene")}
          >
            {view === "scene" ? (
              <Table2 className="h-3.5 w-3.5" />
            ) : (
              <BarChart3 className="h-3.5 w-3.5" />
            )}
          </Button>
        )}
        {canEdit && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 shrink-0"
                aria-label={t("canvas.widgetMenu", { widget: title })}
                // Stops a click on the menu from starting a drag.
                onPointerDown={(event) => event.stopPropagation()}
              >
                <MoreVertical className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onConfigure?.(widget.id)}>
                <Settings2 className="h-4 w-4" />
                {t("canvas.configure")}
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive" onSelect={() => onRemove?.(widget.id)}>
                <Trash2 className="h-4 w-4" />
                {t("canvas.remove")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </header>

      <div className="min-h-0 flex-1 p-2">
        {unconfigured ? (
          <UnconfiguredNotice canEdit={canEdit} onConfigure={() => onConfigure?.(widget.id)} />
        ) : restricted ? (
          <RestrictedNotice />
        ) : (
          <WidgetTile
            type={widget.type}
            data={data}
            config={widget.options}
            slots={slots}
            source={moduleSource}
            errorCode={errorCode}
            isLoading={isLoading || (isPluginWidget && pluginCatalogQuery.isLoading)}
            now={sampleData ? SAMPLE_NOW : undefined}
            view={drawable ? view : "table"}
            chromeless
          />
        )}
      </div>
    </section>
  );
}

/** A binding with empty slots — an installed listing before someone points it
 *  at this community's counter. Not an error, a next step, and one only an author
 *  can take. */
function UnconfiguredNotice({
  canEdit,
  onConfigure,
}: {
  canEdit: boolean;
  onConfigure: () => void;
}) {
  const { t } = useTranslation("dashboards");
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center">
      <p className="text-muted-foreground text-sm">{t("canvas.unconfigured")}</p>
      <p className="text-muted-foreground/80 text-xs">{t("canvas.unconfiguredHint")}</p>
      {canEdit && (
        <Button size="sm" variant="outline" onClick={onConfigure}>
          {t("canvas.configure")}
        </Button>
      )}
    </div>
  );
}

/** The binding resolved and its target is not there for this viewer.
 *
 * Deliberately says nothing about what the target was — not its name, not its
 * id, not its kind beyond the source already on the provenance line. And
 * deliberately offers no Configure button: nothing here is misconfigured. */
function RestrictedNotice() {
  const { t } = useTranslation("dashboards");
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 p-3 text-center">
      <EyeOff className="h-4 w-4 text-muted-foreground" aria-hidden />
      <p className="text-muted-foreground text-sm">{t("canvas.restricted")}</p>
      <p className="text-muted-foreground/80 text-xs">{t("canvas.restrictedHint")}</p>
    </div>
  );
}

/**
 * The line under a widget's title that says what it is showing.
 *
 * Chrome, therefore app code: a widget draws inside its box and can neither
 * suppress this line nor influence a word of it. That matters because the line
 * is what a reader trusts when the numbers look wrong — a widget that could
 * write its own provenance could describe data it is not drawing.
 *
 * What it may say is bounded by `provenance.ts`: the datasets the statement
 * read, as the server resolved them for the person reading it.
 */

import { AlertTriangle, Info, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { DataMeta } from "@/lib/widgets/dataShapes";
import { queryScope } from "@/lib/widgets/provenance";
import { sourceDescriptor } from "@/lib/widgets/sources";
import { localized, type WidgetMeta } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

export interface WidgetProvenanceProps {
  binding: WidgetBinding;
  meta?: DataMeta;
  /** The datasets the statement read, as the server resolved them. */
  relations?: string[];
  /** The widget's own display options, and the module's `meta` so each one can
   *  be named in the widget's own words rather than by its key. */
  options?: Record<string, string>;
  widgetMeta?: WidgetMeta | null;
  /** Re-run the widget's own queries. Absent on a preview, which has none. */
  onRefresh?: () => void;
  className?: string;
}

export function WidgetProvenance({
  binding,
  relations,
  meta,
  options,
  widgetMeta,
  onRefresh,
  className,
}: WidgetProvenanceProps) {
  const { t, i18n } = useTranslation(["dashboards", "tasks", "common"]);

  // What a statement read, answered by the server rather than parsed here: what
  // a statement resolves to is the validator's answer, and a second reading of
  // the same SQL could only disagree with it.
  const scope = useMemo(() => queryScope(relations ?? []), [relations]);

  const descriptor = sourceDescriptor(binding.source);
  const sourceLabel = t(`dashboards:bindingSource.${binding.source}` as const);

  // The compact line: source, then the one or two things that narrow it, then
  // how much came back. Everything else waits in the popover.
  const parts: string[] = [sourceLabel];
  for (const chip of scope) {
    parts.push(chip.label);
  }
  if (typeof meta?.total === "number" && descriptor) {
    parts.push(
      t(`dashboards:provenance.rows_${descriptor.rowNoun}` as const, { count: meta.total })
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex min-w-0 items-center gap-1 truncate text-left text-muted-foreground text-xs hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            className
          )}
          aria-label={t("dashboards:provenance.open")}
          // A click on the line must not start a canvas drag.
          onPointerDown={(event) => event.stopPropagation()}
        >
          {meta?.truncated && (
            <AlertTriangle
              className="h-3 w-3 shrink-0 text-yellow-600 dark:text-yellow-400"
              aria-hidden
            />
          )}
          <span className="truncate">{parts.join(" · ")}</span>
          <Info className="h-3 w-3 shrink-0 opacity-0 group-hover/widget:opacity-60" aria-hidden />
        </button>
      </PopoverTrigger>

      <PopoverContent align="start" className="w-80 space-y-3 text-sm">
        <h4 className="font-semibold">{t("dashboards:provenance.title")}</h4>

        <Row label={t("dashboards:provenance.source")}>{sourceLabel}</Row>

        {scope.length > 0 && (
          <Row label={t("dashboards:provenance.scope")}>
            <ul className="space-y-0.5">
              {scope.map((chip) => (
                <li key={chip.key}>{chip.label}</li>
              ))}
            </ul>
          </Row>
        )}

        {typeof meta?.total === "number" && descriptor && (
          <Row label={t("dashboards:provenance.showing")}>
            {t(`dashboards:provenance.rows_${descriptor.rowNoun}` as const, { count: meta.total })}
            {meta.truncated && (
              <span className="mt-1 block text-muted-foreground text-xs">
                {t("dashboards:provenance.cappedHint", { count: meta.total })}
              </span>
            )}
          </Row>
        )}

        {/* Display options, so a read-only viewer can see how the widget is set
            up — until now they were visible only inside the write-gated dialog. */}
        {options && Object.keys(options).length > 0 && (
          <Row label={t("dashboards:provenance.display")}>
            <ul className="space-y-0.5">
              {Object.entries(options).map(([key, value]) => (
                <li key={key}>
                  {localized(widgetMeta?.options?.[key]?.label, i18n.language) ?? key}:{" "}
                  {localized(widgetMeta?.options?.[key]?.values?.[value], i18n.language) ?? value}
                </li>
              ))}
            </ul>
          </Row>
        )}

        {onRefresh && (
          <Button variant="outline" size="sm" className="w-full" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5" />
            {t("dashboards:provenance.refresh")}
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5rem_1fr] gap-2">
      <span className="text-muted-foreground text-xs">{label}</span>
      <div className="min-w-0 break-words text-xs">{children}</div>
    </div>
  );
}

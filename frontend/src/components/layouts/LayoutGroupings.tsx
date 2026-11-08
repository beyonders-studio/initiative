import type { GroupingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Eye, EyeClosed } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { DateBucket, LayoutGrouping } from "@/api/generated/initiativeAPI.schemas";
import { useGroupables } from "@/hooks/useTaskGroupings";
import type { ListLayout } from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import {
  DATE_BUCKETS,
  groupingsFor,
  groupingsOf,
  MAX_GROUPINGS,
  MAX_HIDDEN_GROUPS,
  type OfferedGrouping,
} from "@/lib/layouts/grouping";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import type { LayoutEdits } from "./LayoutEditor";

const NOT_GROUPED = "__none__";

/** What a date is grouped by until somebody picks another bucket. */
const FIRST_BUCKET: DateBucket = "week";

/**
 * What a list offers to group by: every field whose values group, ticked
 * where the list offers it, in the order it offers them, a date's with the
 * bucket of the calendar it groups by, and the one everyone starts on. Saved
 * with the layout.
 */
export const LayoutGroupings = ({
  layout,
  fields,
  edits,
}: {
  layout: ListLayout;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const groupable = useGroupables(fields, translate);
  const all = useMemo(() => groupingsFor(groupable, layout.kind), [groupable, layout.kind]);
  const { groupings, group_by: groupBy = null } = layout.definition;
  const entries = groupingsOf(groupings, layout.kind, groupable);
  const byId = new Map(all.map((each) => [each.id, each]));
  const ticked = entries.flatMap((entry) => byId.get(entry.field) ?? []);
  const unticked = all.filter((each) => !entries.some((entry) => entry.field === each.id));
  const full = entries.length >= MAX_GROUPINGS;

  const change = (next: LayoutGrouping[], startsOn: string | null = groupBy) =>
    edits.changeGroupings(
      next,
      startsOn !== null && next.some((entry) => entry.field === startsOn) ? startsOn : null
    );
  // Moves the offered grouping at `index` by `by` among the ones shown.
  const move = (index: number, by: number) => {
    const from = entries.findIndex((entry) => entry.field === ticked[index].id);
    const to = entries.findIndex((entry) => entry.field === ticked[index + by].id);
    const next = [...entries];
    [next[from], next[to]] = [next[to], next[from]];
    change(next);
  };
  // A date's groups are its buckets, so the ones it left out go with them.
  const rebucket = (id: string, bucket: DateBucket) =>
    change(entries.map((entry) => (entry.field === id ? { field: id, bucket } : entry)));

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{translate("layouts:groupings.heading")}</h3>
        <p className="text-muted-foreground text-xs">{translate("layouts:groupings.help")}</p>
      </div>
      <ul className="space-y-1">
        {ticked.map((grouping, index) => (
          <li key={grouping.id} className="flex items-center gap-2">
            <Checkbox
              id={`grouping-${grouping.id}`}
              checked
              onCheckedChange={() => change(entries.filter((entry) => entry.field !== grouping.id))}
            />
            <Label htmlFor={`grouping-${grouping.id}`} className="min-w-0 flex-1 truncate">
              {grouping.label}
            </Label>
            {grouping.bucket ? (
              <Select
                value={entries.find((entry) => entry.field === grouping.id)?.bucket ?? FIRST_BUCKET}
                onValueChange={(value) => rebucket(grouping.id, value as DateBucket)}
              >
                <SelectTrigger
                  className="h-7 w-28"
                  aria-label={translate("layouts:groupings.bucket", { name: grouping.label })}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DATE_BUCKETS.map((bucket) => (
                    <SelectItem key={bucket} value={bucket}>
                      {translate(`layouts:groupings.buckets.${bucket}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={translate("layouts:groupings.moveUp", { name: grouping.label })}
              disabled={index === 0}
              onClick={() => move(index, -1)}
            >
              <ArrowUp className="h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={translate("layouts:groupings.moveDown", { name: grouping.label })}
              disabled={index === ticked.length - 1}
              onClick={() => move(index, 1)}
            >
              <ArrowDown className="h-3.5 w-3.5" />
            </Button>
          </li>
        ))}
        {unticked.map((grouping) => (
          <li key={grouping.id} className="flex items-center gap-2">
            <Checkbox
              id={`grouping-${grouping.id}`}
              checked={false}
              disabled={full}
              onCheckedChange={() =>
                change([
                  ...entries,
                  grouping.bucket
                    ? { field: grouping.id, bucket: FIRST_BUCKET }
                    : { field: grouping.id },
                ])
              }
            />
            <Label htmlFor={`grouping-${grouping.id}`} className="min-w-0 flex-1 truncate">
              {grouping.label}
            </Label>
          </li>
        ))}
      </ul>
      {full && unticked.length > 0 ? (
        <p className="text-muted-foreground text-xs">
          {translate("layouts:groupings.full", { count: MAX_GROUPINGS })}
        </p>
      ) : null}
      <Field label={translate("layouts:groupings.startsOn")} className="space-y-1">
        <Select
          value={groupBy ?? NOT_GROUPED}
          onValueChange={(value) => change(entries, value === NOT_GROUPED ? null : value)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NOT_GROUPED}>{translate("layouts:groupings.notGrouped")}</SelectItem>
            {ticked.map((grouping) => (
              <SelectItem key={grouping.id} value={grouping.id}>
                {grouping.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    </div>
  );
};

/**
 * What the canvas is grouped by, picked from what the list offers, and the
 * groups of it, every one, hidden ones included: clicking one leaves it out
 * of the list, or puts it back.
 */
export const CanvasGrouping = ({
  offered,
  active,
  grouping: picked,
  onGroupingChange,
  disabled,
  onToggle,
}: {
  offered: OfferedGrouping[];
  /** The grouping picked, once its groups are in. */
  active?: OfferedGrouping;
  grouping: GroupingState;
  onGroupingChange: (next: GroupingState) => void;
  /** A save is under way, and nothing changes until it answers. */
  disabled: boolean;
  onToggle: (id: string, key: string, shown: boolean) => void;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const pickedColumn = offered.find((each) => picked.includes(each.grouping.column))?.grouping
    .column;
  const hiddenFull = (active?.hidden.size ?? 0) >= MAX_HIDDEN_GROUPS;
  // Every group there is, the hidden ones among them.
  const keys = useMemo(() => {
    if (!active) return [];
    const { grouping, hidden } = active;
    return [...new Set([...(grouping.values ?? []), ...hidden])].sort(grouping.compare);
  }, [active]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Label htmlFor="canvas-group-by" className="text-sm">
        {t("layouts:groupings.heading")}
      </Label>
      <Select
        value={pickedColumn ?? NOT_GROUPED}
        onValueChange={(value) => onGroupingChange(value === NOT_GROUPED ? [] : [value])}
      >
        <SelectTrigger id="canvas-group-by" className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NOT_GROUPED}>{t("layouts:groupings.notGrouped")}</SelectItem>
          {offered.map(({ grouping }) => (
            <SelectItem key={grouping.id} value={grouping.column}>
              {grouping.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {active ? (
        <>
          <span className="text-muted-foreground text-sm">{t("layouts:groupings.shown")}</span>
          {keys.map((key) => {
            const shown = !active.hidden.has(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={shown}
                disabled={disabled || (shown && hiddenFull)}
                onClick={() => onToggle(active.grouping.id, key, !shown)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-1",
                  !shown && "border-dashed opacity-50"
                )}
              >
                {shown ? (
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <EyeClosed className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {active.grouping.header(key)}
              </button>
            );
          })}
          {hiddenFull ? (
            <p className="w-full text-muted-foreground text-xs">
              {t("layouts:groupings.hiddenFull", { count: MAX_HIDDEN_GROUPS })}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

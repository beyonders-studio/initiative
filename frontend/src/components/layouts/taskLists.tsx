/**
 * A project's lists as the layout editor lays them out: the project whose
 * they are, and what each list is grouped by and the limits a board sets on
 * its columns.
 */

import { useTranslation } from "react-i18next";

import type { TaskStatusRead, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { MAX_COLUMN_LIMIT } from "@/hooks/useColumnLimits";
import { Label } from "@/ui/label";
import type { ListLayout } from "@/ui/layouts/draft";
import type { FieldDef } from "@/ui/layouts/fields";

import type { LayoutEdits } from "./LayoutEditor";
import { LayoutGroupings } from "./LayoutGroupings";
import { CommittedInput } from "./LayoutSettingsPanel";

/** The project whose layouts are open: whose statuses its preview draws. */
export type LayoutProject = {
  id: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** Its task types, each with a page of its own. */
  types: TaskTypeRead[];
};

/** A project's list settings of its own: what a list offers to group by,
 *  beside a calendar, and how many open tasks each of a board's columns
 *  takes. */
export const TaskListSettings = ({
  layout,
  fields,
  statuses,
  edits,
}: {
  layout: ListLayout;
  fields: ReadonlyMap<string, FieldDef>;
  /** The project's statuses, whose board columns can be limited. */
  statuses: TaskStatusRead[];
  edits: LayoutEdits;
}) => (
  <>
    {layout.kind !== "calendar" ? (
      <LayoutGroupings layout={layout} fields={fields} edits={edits} />
    ) : null}
    {layout.kind === "board" ? (
      <ColumnLimits layout={layout} statuses={statuses} edits={edits} />
    ) : null}
  </>
);

/** A limit as typed, as the layout keeps it: a whole number the server takes,
 *  or nothing for no limit; null for anything else, which puts back the
 *  stored one. */
const limitText = (text: string): string | null => {
  if (text === "") return "";
  const limit = Number(text);
  return Number.isInteger(limit) && limit >= 1 && limit <= MAX_COLUMN_LIMIT ? String(limit) : null;
};

/** How many open tasks each of a board's columns takes from a person; one
 *  left empty takes any number. Saved with the layout. */
const ColumnLimits = ({
  layout,
  statuses,
  edits,
}: {
  layout: ListLayout;
  statuses: TaskStatusRead[];
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation("layouts");
  const limits = new Map(
    (layout.definition.limits ?? []).map((each) => [each.status_id, each.limit])
  );
  const change = (statusId: number, text: string) => {
    const next = new Map(limits);
    if (text === "") next.delete(statusId);
    else next.set(statusId, Number(text));
    edits.changeLimits(
      statuses.flatMap((status) => {
        const kept = next.get(status.id);
        return kept === undefined ? [] : [{ status_id: status.id, limit: kept }];
      })
    );
  };
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{t("limits.heading")}</h3>
        <p className="text-muted-foreground text-xs">{t("limits.help")}</p>
      </div>
      <ul className="space-y-2">
        {statuses.map((status) => (
          <li key={status.id} className="flex items-center gap-2">
            <Label htmlFor={`column-limit-${status.id}`} className="min-w-0 flex-1">
              <TaskStatusOption status={status} />
            </Label>
            <div className="w-20">
              <CommittedInput
                id={`column-limit-${status.id}`}
                value={String(limits.get(status.id) ?? "")}
                optional
                numeric
                normalize={limitText}
                onCommit={(text) => change(status.id, text)}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

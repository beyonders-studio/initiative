/**
 * Building a query by clicking.
 *
 * A dashboard has to be buildable by somebody who does not write SQL, so this
 * is the primary way a widget is bound and the statement is what it produces —
 * not the other way round. What is chosen here is a *description*: which
 * dataset, which columns, what narrows it, what it is grouped by. The server
 * writes the SQL from that description and hands back both the statement to
 * store and the columns the widget's slots can be filled from.
 *
 * The SQL is shown, read-only, because somebody should be able to see what
 * their clicking produced — and because it is the thing that gets stored.
 *
 * What it reads is one of the registry's datasets or a range of one of the
 * initiative's spreadsheets. A range's columns are whatever its header says, so
 * they come from the server's answer to the description rather than from the
 * registry, and choosing a range starts with every one of them.
 */

import { Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  DatasetName,
  type QueryBuildRequest,
  type QueryColumnSpec,
  type QuerySheetDescription,
  type QuerySheetSpec,
} from "@/api/generated/initiativeAPI.schemas";
import { FilterBuilder, fieldLabel } from "@/components/initiativeTools/dashboards/FilterBuilder";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import { useFieldCatalogs } from "@/hooks/useQueryVocabulary";
import { listFormat } from "@/lib/intl";
import { joinRange, splitRange } from "@/lib/spreadsheet/range";
import { type FilterLeaf, type FilterNode, toFilterFieldSpec } from "@/lib/widgets/conditions";

/** The datasets a query may name. Read from the generated enum, which is the
 *  backend's own registry — so a dataset declared there is offered here on the
 *  next generation rather than after an edit to a second list. */
const DATASETS = Object.values(DatasetName) as DatasetName[];

/** What a column may be reduced to, mirroring the builder's own set. */
const AGGREGATES = ["count", "sum", "avg", "min", "max"] as const;
/** What may be added up along the grouping, mirroring the builder's set. */
const RUNNING = ["count", "sum"] as const;
/** How a running aggregate is held in the "Show as" choice. */
const RUNNING_PREFIX = "running_";
const BUCKETS = ["day", "week", "month", "quarter", "year"] as const;

/** The one column that is not a field: how many rows there are. */
const COUNT_ALL: QueryColumnSpec = { field: "*", aggregate: "count", alias: "count" };

/** The dataset picker's choice for a range of a spreadsheet. */
const SPREADSHEET = "sheet";
/** The sheet picker's choice for a range that names no sheet. */
const FIRST_SHEET = "";

/** What a statement is grouped by: once any column is a count or a total,
 *  every column shown as it is — the only grouping Postgres accepts, so it is
 *  worked out rather than asked for. With no count or total, every row shows.
 *  A name is listed once: the server groups every column that has it, such as
 *  one date rounded two ways. */
const groupingFor = (columns: QueryColumnSpec[]): string[] =>
  columns.some((column) => column.aggregate)
    ? [
        ...new Set(
          columns
            .filter((column) => !column.aggregate && column.field !== "*")
            .map((column) => column.alias || column.field)
        ),
      ]
    : [];

export interface QueryBuilderProps {
  spec: QueryBuildRequest;
  onChange: (spec: QueryBuildRequest) => void;
  /** The dashboard's initiative. Every list a filter picks from is its own. */
  initiativeId: number;
  /** The initiative's spreadsheets, for a description that reads a range. */
  spreadsheets: readonly { id: number; name: string }[];
  /** What the server read of the range the description names: the workbook's
   *  sheets and the range's columns. Absent until it has answered for this
   *  description. */
  sheet?: QuerySheetDescription;
}

export function QueryBuilder({
  spec,
  onChange,
  initiativeId,
  spreadsheets,
  sheet,
}: QueryBuilderProps) {
  const { t, i18n } = useTranslation(["dashboards", "common"]);
  const reading = spec.sheet ?? null;
  const catalog = useFieldCatalog(spec.dataset as DatasetName);
  const { relations, defaultFilters } = catalog;
  // A range's columns are named by its header as written, so each carries its
  // name as its label rather than being worded as a registry field.
  const fields = useMemo(
    () =>
      reading
        ? (sheet?.fields ?? []).map((field) => ({ ...toFilterFieldSpec(field), label: field.name }))
        : catalog.fields,
    [reading, sheet, catalog.fields]
  );
  // What each related dataset holds. A relation says only its name and where
  // it arrives; what may be named there is that dataset's own description, so
  // it is read the same way this one is.
  const related = useFieldCatalogs(relations.map((relation) => relation.dataset));

  // Only what a statement can actually select: a computed field has no column
  // for a SELECT to read, and offering one would produce a query the server
  // then refuses.
  const selectable = useMemo(
    () => fields.filter((field) => reading || !field.field.endsWith("_ids")),
    [fields, reading]
  );

  /** What a related dataset offers, prefixed with the relation that reaches
   *  it — which is exactly how a statement names one. */
  const reachable = useMemo(
    () =>
      relations.flatMap((relation) => {
        const holder = related.find((entry) => entry.dataset === relation.dataset);
        return (holder?.fields ?? [])
          .filter((field) => !field.name.endsWith("_ids"))
          .map((field) => ({
            name: `${relation.name}.${field.name}`,
            type: field.type,
            relation: relation.name,
          }));
      }),
    [relations, related]
  );

  const byName = useMemo(
    () =>
      new Map<string, { kind?: string; label?: string }>([
        ...selectable.map((field) => [field.field, field] as const),
        ...reachable.map((field) => [field.name, { kind: field.type }] as const),
      ]),
    [selectable, reachable]
  );

  const labelOf = (name: string) => byName.get(name)?.label ?? fieldLabel(name, t);

  const patch = (next: Partial<QueryBuildRequest>) => {
    const merged = { ...spec, ...next };
    onChange({ ...merged, group_by: groupingFor(merged.columns) });
  };
  // What the statement is grouped by now. A saved widget keeps the grouping it
  // was built with until it is edited, because opening one must not rewrite
  // it, so this reads the spec rather than working it out again.
  const grouping = spec.group_by ?? [];

  /**
   * A new statement starts without archived work or templates.
   *
   * Seeded here rather than written into the starting spec because the answer
   * belongs to the dataset and arrives with its catalog. Choosing a different
   * dataset clears the filters — nothing chosen against the old one survives —
   * so the new one seeds its own, and coming back to a dataset seeds it again.
   *
   * What is remembered is the dataset last seeded, which is what separates
   * that from an author deleting the conditions: the filters are ordinary
   * rows, and removing them is how somebody asks about archived work. Deleting
   * them leaves the dataset unchanged, so nothing puts them back.
   */
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    // Empty while the catalog is on its way, and for a dataset that has
    // neither lifecycle. Neither is a dataset we have seeded.
    if (!defaultFilters.length) return;
    if (seededFor.current === spec.dataset) return;
    seededFor.current = spec.dataset ?? null;
    if (spec.where?.length) return;
    onChange({ ...spec, where: defaultFilters.map((condition) => ({ ...condition })) });
  }, [defaultFilters, spec, onChange]);

  /**
   * A range starts with every one of its columns, shown as it is.
   *
   * Seeded once its columns arrive, for each range in turn: choosing another
   * file, sheet or range starts over, while removing columns from this one
   * leaves the range unchanged, so nothing puts them back.
   */
  const seededRange = useRef<string | null>(null);
  useEffect(() => {
    if (!reading || !sheet?.fields.length) return;
    const key = `${reading.file}:${reading.range ?? ""}`;
    if (seededRange.current === key) return;
    seededRange.current = key;
    if (spec.columns.some((column) => column.field !== "*")) return;
    onChange({
      ...spec,
      columns: sheet.fields.map((field) => ({ field: field.name })),
      group_by: [],
    });
  }, [reading, sheet, spec, onChange]);

  /** Read another range. Nothing chosen against the old one survives. */
  const read = (next: QuerySheetSpec) =>
    onChange({ sheet: next, columns: [COUNT_ALL], where: [], group_by: [] });
  const parts = splitRange(reading?.range ?? null);
  const sheetNames = sheet?.sheets ?? [];

  const setColumn = (index: number, column: QueryColumnSpec) =>
    patch({ columns: spec.columns.map((held, at) => (at === index ? column : held)) });

  const isDate = (field?: { kind?: string }) => field?.kind === "date";
  /** Whether another column is shown as it is, for this one to add up along. */
  const runsAlong = (index: number) =>
    spec.columns.some((other, at) => at !== index && !other.aggregate && other.field !== "*");

  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <Label>{t("dashboards:builder.dataset")}</Label>
        <Select
          value={reading ? SPREADSHEET : (spec.dataset ?? undefined)}
          onValueChange={(choice) =>
            // A different dataset has different fields, so nothing chosen
            // against the old one survives.
            choice === SPREADSHEET
              ? read({ file: spreadsheets[0].id })
              : onChange({ dataset: choice, columns: [COUNT_ALL], where: [], group_by: [] })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DATASETS.map((name) => (
              <SelectItem key={name} value={name}>
                {t(`dashboards:dataset.${name}` as const, { defaultValue: name })}
              </SelectItem>
            ))}
            <SelectItem value={SPREADSHEET} disabled={!spreadsheets.length}>
              {t("dashboards:builder.spreadsheet")}
            </SelectItem>
          </SelectContent>
        </Select>
      </section>

      {reading && (
        <section className="grid grid-cols-pair gap-2">
          <div className="space-y-1">
            <Label>{t("dashboards:builder.spreadsheet")}</Label>
            <Select
              value={String(reading.file)}
              onValueChange={(file) => read({ file: Number(file) })}
            >
              <SelectTrigger aria-label={t("dashboards:builder.spreadsheet")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {spreadsheets.map((file) => (
                  <SelectItem key={file.id} value={String(file.id)}>
                    {file.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>{t("dashboards:builder.sheet")}</Label>
            <Select
              value={parts.sheet ?? FIRST_SHEET}
              onValueChange={(name) =>
                read({ ...reading, range: joinRange(name || null, parts.cells) })
              }
            >
              <SelectTrigger aria-label={t("dashboards:builder.sheet")}>
                <SelectValue placeholder={t("dashboards:builder.firstSheet")} />
              </SelectTrigger>
              <SelectContent>
                {[...new Set([...(parts.sheet ? [parts.sheet] : []), ...sheetNames])].map(
                  (name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  )
                )}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="builder-range">{t("dashboards:builder.range")}</Label>
            <Input
              id="builder-range"
              key={`${reading.file}:${reading.range ?? ""}`}
              defaultValue={parts.cells}
              placeholder="A1:D"
              onBlur={(event) => {
                const range = joinRange(parts.sheet, event.target.value);
                if (range !== (reading.range ?? null)) read({ ...reading, range });
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.currentTarget.blur();
              }}
            />
            <p className="text-muted-foreground text-xs">{t("dashboards:builder.rangeHelp")}</p>
          </div>
        </section>
      )}

      <section className="space-y-2">
        <Label>{t("dashboards:builder.columns")}</Label>
        {spec.columns.map((column, index) => (
          // Two columns may read the same field (a count of it and the field
          // itself), so the position is what tells the rows apart.
          // biome-ignore lint/suspicious/noArrayIndexKey: position is the identity here
          <div key={index} className="flex items-center gap-2">
            <Select
              value={column.field}
              onValueChange={(fieldName) =>
                setColumn(index, {
                  ...column,
                  field: fieldName,
                  // A rounding that meant something for a date means nothing
                  // for the column that replaced it.
                  bucket: isDate(byName.get(fieldName)) ? column.bucket : null,
                  alias: null,
                })
              }
            >
              <SelectTrigger className="flex-1" aria-label={t("dashboards:builder.field")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="*">{t("dashboards:builder.everyRow")}</SelectItem>
                {selectable.map((field) => (
                  <SelectItem key={field.field} value={field.field}>
                    {labelOf(field.field)}
                  </SelectItem>
                ))}
                {reachable.map((field) => (
                  <SelectItem key={field.name} value={field.name}>
                    {fieldLabel(field.name, t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={
                column.running
                  ? `${RUNNING_PREFIX}${column.aggregate}`
                  : (column.aggregate ?? "none")
              }
              onValueChange={(choice) => {
                const running = choice.startsWith(RUNNING_PREFIX);
                const aggregate = running ? choice.slice(RUNNING_PREFIX.length) : choice;
                setColumn(index, {
                  ...column,
                  aggregate: aggregate === "none" ? null : aggregate,
                  running: running || undefined,
                  // Named for what it now is: "count" or "running_count".
                  alias: null,
                });
              }}
            >
              <SelectTrigger className="w-32" aria-label={t("dashboards:builder.fn")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("dashboards:builder.asItIs")}</SelectItem>
                {AGGREGATES.map((aggregate) => (
                  <SelectItem key={aggregate} value={aggregate}>
                    {t(`dashboards:aggregate.${aggregate}` as const, {
                      defaultValue: aggregate,
                    })}
                  </SelectItem>
                ))}
                {/* Added up along another column, so offered once there is
                    one. A running column already chosen stays shown, and the
                    builder's refusal says why it no longer runs. */}
                {(column.running || runsAlong(index)) &&
                  RUNNING.map((aggregate) => (
                    <SelectItem
                      key={`${RUNNING_PREFIX}${aggregate}`}
                      value={`${RUNNING_PREFIX}${aggregate}`}
                    >
                      {t(`dashboards:aggregate.${RUNNING_PREFIX}${aggregate}` as const)}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>

            {isDate(byName.get(column.field)) && (
              <Select
                value={column.bucket ?? "none"}
                onValueChange={(bucket) =>
                  setColumn(index, { ...column, bucket: bucket === "none" ? null : bucket })
                }
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("dashboards:builder.exactTime")}</SelectItem>
                  {BUCKETS.map((bucket) => (
                    <SelectItem key={bucket} value={bucket}>
                      {t(`dashboards:bucket.${bucket}` as const, { defaultValue: bucket })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              aria-label={t("dashboards:builder.removeColumn")}
              disabled={spec.columns.length <= 1}
              onClick={() => patch({ columns: spec.columns.filter((_held, at) => at !== index) })}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            patch({
              columns: [
                ...spec.columns,
                selectable[0] ? { field: selectable[0].field } : COUNT_ALL,
              ],
            })
          }
        >
          <Plus className="h-4 w-4" />
          {t("dashboards:builder.addColumn")}
        </Button>
      </section>

      <section className="space-y-2">
        <Label>{t("common:toolbar.filters")}</Label>
        <FilterBuilder
          fields={fields}
          defaults={defaultFilters as unknown as FilterLeaf[]}
          loading={reading ? !sheet : catalog.isLoading}
          initiativeId={initiativeId}
          value={(spec.where ?? []) as FilterNode[]}
          onChange={(where) => patch({ where })}
        />
      </section>

      <section className="space-y-1">
        <Label>{t("dashboards:builder.groupBy")}</Label>
        <p className="text-sm">
          {grouping.length
            ? t("dashboards:builder.groupedBy", {
                columns: listFormat(i18n.resolvedLanguage ?? i18n.language, {
                  type: "conjunction",
                }).format(grouping.map(labelOf)),
              })
            : t("dashboards:builder.notGrouped")}
        </p>
        <p className="text-muted-foreground text-xs">{t("dashboards:builder.groupByHelp")}</p>
      </section>
    </div>
  );
}

/**
 * Authoring the filter half of a data view.
 *
 * This is the narrowing half of the Build step: which rows the tile is about,
 * beside which columns it reads. What it produces is a description, and the
 * server writes the SQL from it — so a filter clicked together here is a
 * statement the query surface will run.
 *
 * Two decisions worth stating:
 *
 * **One choice, said once.** The rows either all have to match or any one
 * may, and the author picks which at the top; a group inside asks the other
 * question. "Any" is stored as one OR group, so the description is still the
 * plain filter tree the server reads. The dataset's lifecycle defaults (not
 * archived, not a template) are a leave out / include / only choice above the
 * rows rather than rows, so
 * choosing "any" never turns them into "archived or not".
 *
 * **Dates are relative unless you ask otherwise.** A dashboard is a standing
 * question, not a snapshot; "due in the next 30 days" stays true and
 * "due before 30 September" is wrong by October. Absolute is still there for
 * the cases that mean a real date — a launch, a quarter end.
 *
 * Every value control is the app's own: the same status, priority, member and
 * tag primitives the task filters use, over lists the viewer can already see.
 */

import type { TFunction } from "i18next";
import { Plus, X } from "lucide-react";
import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useProjects, useTaskTypesOf } from "@/hooks/useProjects";
import { useProperties } from "@/hooks/useProperties";
import { useTags } from "@/hooks/useTags";
import { useSearchMembers } from "@/hooks/useUsers";
import { toolViewParams } from "@/lib/tools";
import {
  type ConditionValue,
  type FilterFieldSpec,
  type FilterLeaf,
  type FilterNode,
  type FilterOp,
  fieldSpec,
  isGroup,
  isRelativeDate,
  optionLabelKey,
} from "@/lib/widgets/conditions";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { MemberPicker, type MemberScope } from "@/ui/member-picker";
import { SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

export interface FilterBuilderProps {
  value: FilterNode[];
  onChange: (next: FilterNode[]) => void;
  /** The dashboard's initiative — every option list below is its own. */
  initiativeId: number;
  /** What a row may be read against: the fields of what is being filtered. */
  fields: readonly FilterFieldSpec[];
  /** What a new statement leaves out until its author says otherwise. */
  defaults: readonly FilterLeaf[];
  /** Whether the fields are still on their way. */
  loading: boolean;
}

/** The value control a field starts empty at: a list for a picker that takes
 *  several, today for a date, nothing for the rest. */
const blankValue = (spec?: FilterFieldSpec): ConditionValue =>
  spec?.multiple ? [] : spec?.kind === "date" ? { relative: 0 } : "";

/** A condition to start from, over whatever this dataset holds. There is no
 *  field every dataset has, so the first one it offers is the one to draw. */
const emptyLeaf = (fields: readonly FilterFieldSpec[]): FilterLeaf => {
  const first = fields[0];
  return {
    field: first?.field ?? "",
    op: first?.ops[0] ?? "eq",
    value: blankValue(first),
  };
};

/** A field's label, falling back to its name.
 *
 *  The names come from the server now, so they cannot be checked against the
 *  locale file at compile time the way a literal union was. A missing label
 *  therefore degrades to the field's own name — readable, and visible enough in
 *  review to be fixed — rather than rendering a raw i18n key. */
export const fieldLabel = (
  name: string,
  t: TFunction<readonly ["dashboards", "common"]> | TFunction
): string => {
  // A field reached through a relation reads "Project › Name".
  if (name.includes(".")) {
    return name
      .split(".")
      .map((part) => fieldLabel(part, t))
      .join(" › ");
  }
  const spaced =
    name
      .replace(/_ids?$/, "")
      .replace(/_/g, " ")
      .trim() || name;
  return (t as TFunction)(`dashboards:filterField.${name}` as never, {
    defaultValue: spaced.charAt(0).toUpperCase() + spaced.slice(1),
  }) as string;
};

/** Whether a top-level condition is one of the dataset's lifecycle defaults —
 *  "not archived", "not a template" — or its opposite. Those are offered as a
 *  choice above the rows rather than as rows, so the match-all/any choice
 *  below never applies to them. */
const sameLeaf = (node: FilterNode, wanted: FilterLeaf): boolean =>
  !isGroup(node) &&
  node.field === wanted.field &&
  node.op === wanted.op &&
  JSON.stringify(node.value) === JSON.stringify(wanted.value) &&
  !node.negate;

/** Leave the archived (or templates) out, count them too, or count only them. */
export type Lifecycle = "exclude" | "include" | "only";

/** The opposite of a default: both are yes/no questions ("is it unarchived",
 *  "is it not a template"), so asking only for the others is the same
 *  comparison with the answer flipped. */
const onlyLeaf = (leaf: FilterLeaf): FilterLeaf => ({ ...leaf, value: !leaf.value });

const lifecycleOf = (value: FilterNode[], leaf: FilterLeaf): Lifecycle =>
  value.some((node) => sameLeaf(node, leaf))
    ? "exclude"
    : value.some((node) => sameLeaf(node, onlyLeaf(leaf)))
      ? "only"
      : "include";

/** Which choice a default condition is, by what it reads. */
const defaultLabelKey = (field: string) =>
  field.endsWith("is_template")
    ? ("dashboards:filterBuilder.templates" as const)
    : ("dashboards:filterBuilder.archived" as const);

/**
 * The stored filter, read as the builder draws it: the lifecycle switches that
 * are on, whether the rest must all match or any may, and the rest.
 *
 * "Any" is stored as one OR group at the top, which is exactly what it means;
 * a stored filter of one OR group therefore reads back as "any".
 */
function splitFilters(value: FilterNode[], defaults: readonly FilterLeaf[]) {
  const lifecycle = defaults.map((wanted) => lifecycleOf(value, wanted));
  const rest = value.filter(
    (node) => !defaults.some((wanted) => sameLeaf(node, wanted) || sameLeaf(node, onlyLeaf(wanted)))
  );
  const only = rest.length === 1 ? rest[0] : undefined;
  if (only && isGroup(only) && only.logic === "or") {
    return { lifecycle, match: "any" as const, rows: only.conditions };
  }
  return { lifecycle, match: "all" as const, rows: rest };
}

function joinFilters(
  lifecycle: Lifecycle[],
  defaults: readonly FilterLeaf[],
  match: "all" | "any",
  rows: FilterNode[]
): FilterNode[] {
  const kept = defaults.flatMap((leaf, index) =>
    lifecycle[index] === "exclude"
      ? [{ ...leaf }]
      : lifecycle[index] === "only"
        ? [onlyLeaf(leaf)]
        : []
  );
  if (match === "any" && rows.length) return [...kept, { logic: "or", conditions: rows }];
  return [...kept, ...rows];
}

export function FilterBuilder({
  value,
  onChange,
  initiativeId,
  fields,
  defaults,
  loading,
}: FilterBuilderProps) {
  const { t } = useTranslation(["dashboards", "tasks", "common"]);

  // The option lists. Each is a query the canvas or dialog already makes, and
  // each returns only what this viewer can see — so an author cannot filter by
  // something they could not have found in the app anyway.
  const projects = useProjects({ slim: true, ...toolViewParams(Tool.project, "active") });
  const tags = useTags();
  const properties = useProperties({ initiativeId });

  const switchId = useId();

  const options = useMemo(
    () => ({
      project: (projects.data?.items ?? [])
        .filter((project) => project.initiative_id === initiativeId)
        .map((project) => ({ value: String(project.id), label: project.name })),
      tag: (tags.data ?? []).map((tag) => ({ value: String(tag.id), label: tag.name })),
      property: (properties.data ?? []).map((property) => ({
        value: String(property.id),
        label: property.name,
      })),
      // People are searched on the server, among the initiative's members.
      members: { type: "initiative", initiativeId } satisfies MemberScope,
    }),
    [projects.data, tags.data, properties.data, initiativeId]
  );

  const { lifecycle, match, rows } = splitFilters(value, defaults);
  const emit = (next: { lifecycle?: Lifecycle[]; match?: "all" | "any"; rows?: FilterNode[] }) =>
    onChange(
      joinFilters(next.lifecycle ?? lifecycle, defaults, next.match ?? match, next.rows ?? rows)
    );

  const replaceAt = (index: number, node: FilterNode | null) => {
    const next = rows.slice();
    if (node === null) next.splice(index, 1);
    else next[index] = node;
    emit({ rows: next });
  };

  // A group inside asks the other question: "any of" these when everything
  // else must match, "all of" these when anything may.
  const groupLogic = match === "all" ? "or" : "and";
  const joiner =
    match === "all" ? t("dashboards:filterBuilder.and") : t("dashboards:filterBuilder.or");

  // Until the declarations arrive, a condition has no field to be read
  // against: its operator list and its value control would both fall back to
  // the plainest thing they can draw, and editing one then rewrites a saved
  // filter into whatever that plain control emitted. So the rows wait.
  if (loading) {
    return (
      <SkeletonRegion>
        <SkeletonLines lines={2} lineClassName="h-9" />
      </SkeletonRegion>
    );
  }

  // A dataset that named no fields has nothing to build a condition from.
  if (!fields.length) {
    return (
      <p className="text-muted-foreground text-xs">{t("dashboards:filterBuilder.noFields")}</p>
    );
  }

  return (
    <div className="space-y-3">
      {defaults.length > 0 && (
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {defaults.map((leaf, index) => (
            <div key={leaf.field} className="flex items-center gap-2">
              <Label htmlFor={`${switchId}-${index}`} className="font-normal text-sm">
                {t(defaultLabelKey(leaf.field))}
              </Label>
              <Select
                value={lifecycle[index]}
                onValueChange={(choice) => {
                  const next = lifecycle.slice();
                  next[index] = choice as Lifecycle;
                  emit({ lifecycle: next });
                }}
              >
                <SelectTrigger id={`${switchId}-${index}`} className="h-8 w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exclude">
                    {t("dashboards:filterBuilder.lifecycleExclude")}
                  </SelectItem>
                  <SelectItem value="include">
                    {t("dashboards:filterBuilder.lifecycleInclude")}
                  </SelectItem>
                  <SelectItem value="only">
                    {t("dashboards:filterBuilder.lifecycleOnly")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>
      )}

      {rows.length === 0 && lifecycle.every((choice) => choice === "include") && (
        <p className="text-muted-foreground text-xs">{t("dashboards:filterBuilder.empty")}</p>
      )}

      {rows.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <span>{t("dashboards:filterBuilder.matchPrefix")}</span>
          <Select value={match} onValueChange={(next) => emit({ match: next as "all" | "any" })}>
            <SelectTrigger className="h-8 w-28" aria-label={t("dashboards:filterBuilder.match")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("dashboards:filterBuilder.matchAll")}</SelectItem>
              <SelectItem value="any">{t("dashboards:filterBuilder.matchAny")}</SelectItem>
            </SelectContent>
          </Select>
          <span>{t("dashboards:filterBuilder.matchSuffix")}</span>
        </div>
      )}

      {rows.map((node, index) => (
        <div
          // Conditions have no id; position is the identity the author sees and
          // edits, and reordering is not offered.
          // biome-ignore lint/suspicious/noArrayIndexKey: positional by design
          key={index}
          className="space-y-2"
        >
          {index > 0 && (
            <p className="text-center font-medium text-muted-foreground text-xs uppercase">
              {joiner}
            </p>
          )}
          <div className="rounded-md border bg-muted/30 p-2">
            {isGroup(node) ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">
                    {node.logic === "or"
                      ? t("dashboards:filterBuilder.groupAny")
                      : t("dashboards:filterBuilder.groupAll")}
                  </Label>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    aria-label={t("dashboards:filterBuilder.remove")}
                    onClick={() => replaceAt(index, null)}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {node.conditions.map((child, childIndex) => (
                  <LeafRow
                    fields={fields}
                    // biome-ignore lint/suspicious/noArrayIndexKey: positional by design
                    key={childIndex}
                    leaf={child as FilterLeaf}
                    options={options}
                    onChange={(next) => {
                      const conditions = node.conditions.slice();
                      if (next === null) conditions.splice(childIndex, 1);
                      else conditions[childIndex] = next;
                      replaceAt(index, conditions.length ? { ...node, conditions } : null);
                    }}
                  />
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    replaceAt(index, {
                      ...node,
                      conditions: [...node.conditions, emptyLeaf(fields)],
                    })
                  }
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t("dashboards:filterBuilder.addToGroup")}
                </Button>
              </div>
            ) : (
              <LeafRow
                leaf={node}
                fields={fields}
                options={options}
                onChange={(next) => replaceAt(index, next)}
              />
            )}
          </div>
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => emit({ rows: [...rows, emptyLeaf(fields)] })}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("dashboards:filterBuilder.add")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            emit({ rows: [...rows, { logic: groupLogic, conditions: [emptyLeaf(fields)] }] })
          }
        >
          {groupLogic === "or"
            ? t("dashboards:filterBuilder.addGroupAny")
            : t("dashboards:filterBuilder.addGroupAll")}
        </Button>
      </div>
    </div>
  );
}

/**
 * The types of the initiative's projects to pick from, each project's read
 * only once a filter on type is there. A type is one project's, so where there
 * are several projects each says whose it is.
 */
function TaskTypeValues({
  projects,
  selected,
  onChange,
}: {
  projects: Options["project"];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const { t } = useTranslation("dashboards");
  const reads = useTaskTypesOf(projects.map((project) => Number(project.value)));
  const choices = projects.flatMap((project, index) =>
    (reads[index]?.data ?? []).map((type) => ({
      value: String(type.id),
      label:
        projects.length > 1
          ? t("filterBuilder.typeInProject", { type: type.name, project: project.label })
          : type.name,
    }))
  );
  return (
    <Combobox
      multiple
      value={selected}
      items={choices}
      placeholder={t("filterBuilder.chooseValue")}
      onValueChange={onChange}
    />
  );
}

type Options = {
  project: { value: string; label: string }[];
  tag: { value: string; label: string }[];
  property: { value: string; label: string }[];
  members: MemberScope;
};

function LeafRow({
  leaf,
  fields,
  options,
  onChange,
}: {
  leaf: FilterLeaf;
  fields: readonly FilterFieldSpec[];
  options: Options;
  onChange: (next: FilterLeaf | null) => void;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const spec = fieldSpec(fields, leaf.field);

  const setField = (field: string) => {
    const next = fieldSpec(fields, field);
    // Changing the field drops the old value rather than carrying a set of tag
    // ids onto a date comparison.
    onChange({ field, op: next?.ops[0] ?? "eq", value: blankValue(next) });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Select value={leaf.field} onValueChange={setField}>
          <SelectTrigger className="h-8 flex-1" aria-label={t("dashboards:filterBuilder.field")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {fields.map((field) => (
              <SelectItem key={field.field} value={field.field}>
                {field.label ?? fieldLabel(field.field, t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {(spec?.ops.length ?? 0) > 1 && (
          <Select value={leaf.op} onValueChange={(op) => onChange({ ...leaf, op: op as FilterOp })}>
            <SelectTrigger className="h-8 w-36" aria-label={t("dashboards:filterBuilder.operator")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(spec?.ops ?? []).map((op) => (
                <SelectItem key={op} value={op}>
                  {t(`dashboards:filterOp.${op}` as const)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0"
          aria-label={t("dashboards:filterBuilder.remove")}
          onClick={() => onChange(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ValueControl
        fields={fields}
        leaf={leaf}
        options={options}
        onChange={(value) => onChange({ ...leaf, value })}
      />
    </div>
  );
}

function ValueControl({
  leaf,
  fields,
  options,
  onChange,
}: {
  leaf: FilterLeaf;
  fields: readonly FilterFieldSpec[];
  options: Options;
  onChange: (value: ConditionValue) => void;
}) {
  const { t } = useTranslation(["dashboards", "tasks", "common", "projects"]);
  const spec = fieldSpec(fields, leaf.field);
  const memberFieldId = useId();
  const searchMembers = useSearchMembers();

  // "Is empty" compares against nothing, so there is nothing to choose.
  if (leaf.op === "is_null") return null;

  if (spec?.kind === "member") {
    // "me" is the language's own word for the reader and stays a string, so
    // the tile answers per person; people travel as numeric ids. A single-value
    // field keeps the one chosen last.
    const multiple = Boolean(spec.multiple);
    const values = multiple
      ? Array.isArray(leaf.value)
        ? leaf.value
        : []
      : leaf.value != null && leaf.value !== ""
        ? [leaf.value as string | number]
        : [];
    const ids = values.filter((value): value is number => typeof value === "number");
    const me = values.includes("me");
    const emit = (nextMe: boolean, nextIds: number[]) =>
      onChange(
        multiple
          ? [...(nextMe ? ["me"] : []), ...nextIds]
          : nextMe
            ? "me"
            : (nextIds[nextIds.length - 1] ?? "")
      );
    return (
      <>
        <Label htmlFor={memberFieldId} className="sr-only">
          {t("dashboards:filterBuilder.value")}
        </Label>
        <MemberPicker
          multiple
          id={memberFieldId}
          searchMembers={searchMembers}
          scope={options.members}
          variant="filter"
          value={ids}
          extras={[
            {
              value: "me",
              label: t("dashboards:provenance.me"),
              selected: me,
              onToggle: (selected) => emit(selected, multiple ? ids : []),
            },
          ]}
          onChange={(next) =>
            emit(multiple && me, multiple ? next : next.filter((id) => !ids.includes(id)))
          }
          placeholder={t("dashboards:filterBuilder.chooseValue")}
          emptyMessage={t("projects:assignee.emptyMessage")}
        />
      </>
    );
  }

  if (spec?.multiple) {
    const list = Array.isArray(leaf.value) ? leaf.value.map(String) : [];
    // A closed vocabulary carries its own values; everything else is a lookup
    // this screen already loads.
    const optionList =
      spec.kind === "select"
        ? (spec.options ?? []).map((value) => ({
            value,
            label: t(optionLabelKey(leaf.field, value), { defaultValue: value }),
          }))
        : spec.kind === "tag"
          ? options.tag
          : spec.kind === "property"
            ? options.property
            : [];
    if (spec.kind === "task_type") {
      return (
        <TaskTypeValues
          projects={options.project}
          selected={list}
          onChange={(values) => onChange(values.map(Number))}
        />
      );
    }
    return (
      <Combobox
        multiple
        value={list}
        items={optionList}
        placeholder={t("dashboards:filterBuilder.chooseValue")}
        // Ids travel as numbers; "me" is the DSL's own token and stays a string.
        onValueChange={(values) =>
          onChange(values.map((value) => (value === "me" ? value : Number(value))))
        }
      />
    );
  }

  if (spec?.kind === "project") {
    return (
      <Select
        value={leaf.value ? String(leaf.value) : ""}
        onValueChange={(value) => onChange(Number(value))}
      >
        <SelectTrigger className="h-8" aria-label={t("dashboards:filterBuilder.value")}>
          <SelectValue placeholder={t("dashboards:filterBuilder.chooseValue")} />
        </SelectTrigger>
        <SelectContent>
          {options.project.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (spec?.kind === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <Switch checked={leaf.value === true} onCheckedChange={(checked) => onChange(checked)} />
        <span className="text-sm">{leaf.value === true ? t("common:yes") : t("common:no")}</span>
      </div>
    );
  }

  if (spec?.kind === "date") {
    const relative = isRelativeDate(leaf.value);
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Select
            value={relative ? "relative" : "absolute"}
            onValueChange={(mode) =>
              onChange(mode === "relative" ? { relative: 0 } : new Date().toISOString())
            }
          >
            <SelectTrigger className="h-8 w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="relative">{t("dashboards:filterBuilder.relative")}</SelectItem>
              <SelectItem value="absolute">{t("dashboards:filterBuilder.absolute")}</SelectItem>
            </SelectContent>
          </Select>

          {relative ? (
            <Input
              type="number"
              className="h-8"
              aria-label={t("dashboards:filterBuilder.relativeDays")}
              value={(leaf.value as { relative: number }).relative}
              onChange={(event) => onChange({ relative: Number(event.target.value) || 0 })}
            />
          ) : (
            <Input
              type="date"
              className="h-8"
              value={typeof leaf.value === "string" ? leaf.value.slice(0, 10) : ""}
              onChange={(event) =>
                onChange(new Date(`${event.target.value}T00:00:00Z`).toISOString())
              }
            />
          )}
        </div>
        {relative && (
          <p className="text-muted-foreground text-xs">
            {t("dashboards:filterBuilder.relativeHint")}
          </p>
        )}
      </div>
    );
  }

  return (
    <Input
      className="h-8"
      value={typeof leaf.value === "string" ? leaf.value : ""}
      placeholder={t("dashboards:filterBuilder.chooseValue")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

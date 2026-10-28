import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  TagRead,
  TagSummary,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import {
  PropertyFilter,
  type PropertyFilterCondition,
} from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useTags } from "@/hooks/useTags";
import type { MemberSearchScope } from "@/hooks/useUsers";
import {
  ASSIGNEE_ME,
  ASSIGNEE_NONE,
  DUE_LABEL_KEYS,
  type DueToken,
  type TaskFilterSpec,
} from "@/lib/filters/taskFilters";
import { pluginFilterFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { PRIORITY_ORDER } from "@/lib/sorting";

/**
 * Task statuses are per-project rows, so filtering by a status *id* only means
 * something inside one project. Categories are the stable vocabulary — which is
 * why a preset like "Incomplete" is expressed with them and survives being
 * shared or copied to another project.
 */
const STATUS_CATEGORIES: readonly TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

/** Categories share one control with the statuses, so their values need a
 *  prefix that can't collide with a numeric status id. */
const CATEGORY_PREFIX = "category:";

/** Which list the filters narrow: one project's tasks, or a person's own
 *  across every community. Each offers what means something there. */
export type TaskFiltersScope =
  | {
      kind: "project";
      /** Whose names the assignee picker offers. */
      memberScope: MemberSearchScope;
      /** The project's statuses; with none, the categories alone are offered. */
      statuses: TaskStatusRead[];
      /** The project's task types; one alone is not offered. */
      types?: TaskTypeRead[];
      /** Scopes the property filter's definitions. */
      initiativeId?: number;
      /** The one project listed, whose metadata the filter offers too. */
      projectId?: number;
    }
  | {
      kind: "mine";
      /** The communities their tasks come from. Tags and statuses are each
       *  community's or project's own, so only categories are offered. */
      communities: { id: number; name: string }[];
    };

type TaskFiltersProps = {
  scope: TaskFiltersScope;
  /** The filter values, as one object — the same shape a preset holds. */
  value: TaskFilterSpec;
  onChange: (next: TaskFilterSpec) => void;
  /** One field above another, for a narrow panel, as against a row that wraps. */
  stacked?: boolean;
};

/**
 * A task list's filters: the same controls on a project and on My Tasks,
 * offering on each what means something there.
 */
export const TaskFilters = ({ scope, value, onChange, stacked = false }: TaskFiltersProps) => {
  const { t } = useTranslation(["projects", "tasks"]);
  const project = scope.kind === "project" ? scope : null;
  const taskStatuses = project?.statuses ?? [];
  const field = stacked ? "w-full space-y-2" : "w-full space-y-2 sm:w-48";
  const { data: tags = [] } = useTags({ enabled: project !== null });

  const patch = (fields: Partial<TaskFilterSpec>) => onChange({ ...value, ...fields });
  // A project's list offers the plug-in fields its readers are drawn there.
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(project?.initiativeId, project !== null);
  const pluginFields = useMemo(
    () => pluginFilterFields(plugins, i18n.language),
    [plugins, i18n.language]
  );

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTags = useMemo(() => {
    const tagMap = new Map(tags.map((tag) => [tag.id, tag]));
    return value.tag_ids
      .map((id) => tagMap.get(id))
      .filter((tag): tag is TagRead => tag !== undefined);
  }, [tags, value.tag_ids]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    patch({ tag_ids: newTags.map((tag) => tag.id) });
  };

  // `me` and `none` are resolved by the server per request, which is what
  // keeps a preset — and a link to it — meaning the same thing for everyone.
  // They are toggles rather than entries in the people picker, which only
  // knows real users.
  const assignedToMe = value.assignees.includes(ASSIGNEE_ME);
  const unassigned = value.assignees.includes(ASSIGNEE_NONE);
  const assigneeIds = value.assignees.filter(
    (entry) => entry !== ASSIGNEE_NONE && entry !== ASSIGNEE_ME
  );

  /** Rebuild the list, keeping the tokens ahead of the ids. */
  const setAssignees = (next: { me?: boolean; none?: boolean; ids?: string[] }) => {
    const me = next.me ?? assignedToMe;
    const none = next.none ?? unassigned;
    patch({
      assignees: [
        ...(none ? [ASSIGNEE_NONE] : []),
        ...(me ? [ASSIGNEE_ME] : []),
        ...(next.ids ?? assigneeIds),
      ],
    });
  };

  return (
    // Bare fields: the surrounding ToolFilterPanel supplies the box, the way it
    // does for every other filter bar.
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        {project ? (
          <div className={field}>
            <Label
              htmlFor="assignee-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.filterByAssignee")}
            </Label>
            <MemberMultiSelect
              id="assignee-filter"
              variant="filter"
              scope={project.memberScope}
              selectedIds={assigneeIds.map(Number).filter(Number.isFinite)}
              onChange={(ids) => setAssignees({ ids: ids.map(String) })}
              tokens={[
                {
                  value: ASSIGNEE_ME,
                  label: t("filters.assignedToMe"),
                  selected: assignedToMe,
                  onToggle: (selected) => setAssignees({ me: selected }),
                },
                {
                  value: ASSIGNEE_NONE,
                  label: t("filters.unassigned"),
                  selected: unassigned,
                  onToggle: (selected) => setAssignees({ none: selected }),
                },
              ]}
              placeholder={t("filters.allAssignees")}
              emptyMessage={t("filters.noUsersAvailable")}
            />
          </div>
        ) : null}
        <div className={field}>
          <Label htmlFor="due-filter" className="block font-medium text-muted-foreground text-xs">
            {t("filters.dueFilter")}
          </Label>
          <Select
            value={value.due ?? "all"}
            onValueChange={(next) => patch({ due: next === "all" ? null : (next as DueToken) })}
          >
            <SelectTrigger id="due-filter">
              <SelectValue placeholder={t("filters.allDueDates")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("filters.allDueDates")}</SelectItem>
              {Object.entries(DUE_LABEL_KEYS).map(([token, labelKey]) => (
                <SelectItem key={token} value={token}>
                  {t(labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className={field}>
          <Label
            htmlFor="status-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByStatus")}
          </Label>
          <MultiSelect
            id="status-filter"
            selectedValues={[
              ...value.status_ids.map(String),
              ...value.status_categories.map((category) => `${CATEGORY_PREFIX}${category}`),
            ]}
            options={[
              ...taskStatuses.map((status) => ({
                value: String(status.id),
                label: status.name,
              })),
              ...STATUS_CATEGORIES.map((category) => ({
                value: `${CATEGORY_PREFIX}${category}`,
                label: t(`filters.category.${category}` as never),
                group: t("filters.statusCategory"),
              })),
            ]}
            onChange={(values) =>
              patch({
                status_ids: values
                  .filter((entry) => !entry.startsWith(CATEGORY_PREFIX))
                  .map(Number)
                  .filter(Number.isFinite),
                status_categories: values
                  .filter((entry) => entry.startsWith(CATEGORY_PREFIX))
                  .map((entry) => entry.slice(CATEGORY_PREFIX.length) as TaskStatusCategory),
              })
            }
            placeholder={t("filters.allStatuses")}
            emptyMessage={t("filters.noStatusesAvailable")}
          />
        </div>
        {project && (project.types?.length ?? 0) > 1 ? (
          <div className={field}>
            <Label
              htmlFor="type-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.filterByType")}
            </Label>
            <MultiSelect
              id="type-filter"
              selectedValues={value.type_ids.map(String)}
              options={(project.types ?? []).map((type) => ({
                value: String(type.id),
                label: type.name,
              }))}
              onChange={(values) => patch({ type_ids: values.map(Number).filter(Number.isFinite) })}
              placeholder={t("filters.allTypes")}
              emptyMessage={t("filters.allTypes")}
            />
          </div>
        ) : null}
        <div className={field}>
          <Label
            htmlFor="priority-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("tasks:filters.filterByPriority")}
          </Label>
          <MultiSelect
            id="priority-filter"
            selectedValues={value.priorities}
            options={PRIORITY_ORDER.map((priority) => ({
              value: priority,
              label: t(`tasks:priority.${priority}` as never),
            }))}
            onChange={(values) => patch({ priorities: values as TaskPriority[] })}
            placeholder={t("tasks:filters.allPriorities")}
            emptyMessage={t("tasks:filters.noPriorities")}
          />
        </div>
        {scope.kind === "mine" ? (
          <div className={field}>
            <Label
              htmlFor="community-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("tasks:filters.filterByCommunity")}
            </Label>
            <MultiSelect
              id="community-filter"
              selectedValues={value.community_ids.map(String)}
              options={scope.communities.map((community) => ({
                value: String(community.id),
                label: community.name,
              }))}
              onChange={(values) =>
                patch({ community_ids: values.map(Number).filter(Number.isFinite) })
              }
              placeholder={t("tasks:filters.allCommunities")}
              emptyMessage={t("tasks:filters.noCommunities")}
            />
          </div>
        ) : null}

        {project ? (
          <>
            <div className={field}>
              <Label
                htmlFor="tag-filter"
                className="block font-medium text-muted-foreground text-xs"
              >
                {t("filters.filterByTag")}
              </Label>
              <TagPicker
                id="tag-filter"
                selectedTags={selectedTags}
                onChange={handleTagsChange}
                placeholder={t("filters.allTags")}
                variant="filter"
              />
            </div>
            <div className={stacked ? "w-full space-y-2" : "w-full space-y-2 sm:w-60"}>
              <Label
                htmlFor="show-archived"
                className="block font-medium text-muted-foreground text-xs"
              >
                {t("filters.archived")}
              </Label>
              <div className="flex h-9 items-center gap-3 rounded-md border bg-background/60 px-3">
                <Switch
                  id="show-archived"
                  checked={value.include_archived}
                  onCheckedChange={(checked) => patch({ include_archived: Boolean(checked) })}
                  aria-label={t("filters.showArchived")}
                />
                <span className="text-muted-foreground text-sm">{t("filters.showArchived")}</span>
              </div>
            </div>
          </>
        ) : null}
      </div>
      <PropertyFilter
        initiativeId={project?.initiativeId}
        owner={project?.projectId ? { kind: "project", id: project.projectId } : undefined}
        value={value.properties}
        plugins={{ fields: pluginFields, value: value.plugins }}
        onChange={(properties: PropertyFilterCondition[], plugins) =>
          patch({ properties, plugins })
        }
      />
    </div>
  );
};

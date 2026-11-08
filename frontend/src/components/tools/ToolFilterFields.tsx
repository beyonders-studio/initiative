/**
 * One filter panel per tool, over that tool's list params.
 *
 * The fields a tool's index page narrows its list with are the fields an
 * export narrows that tool by, so both render them from here: each is a
 * controlled component over the params its list route takes. Controls only a
 * page offers (a sort order, a read state, a favourites switch) are passed in
 * as children and sit in the same row.
 */

import type { FlatNamespace } from "i18next";
import { type ComponentType, type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";

import type {
  ListCalendarsParams,
  ListContactsParams,
  ListCounterGroupsParams,
  ListDashboardsParams,
  ListFilesParams,
  ListPostsParams,
  ListProjectsParams,
  ListWikisParams,
} from "@/api/generated/initiativeAPI.schemas";
import { FileKind, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PropertyFilterParam } from "@/components/properties/PropertyFilter";
import { TagFilterPicker } from "@/components/tags/TagFilterPicker";
import { toolCamelPlural } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Each tool's list params, as its list route takes them. */
type ToolListParams = {
  [Tool.project]: ListProjectsParams;
  [Tool.file]: ListFilesParams;
  [Tool.counter_group]: ListCounterGroupsParams;
  [Tool.calendar]: ListCalendarsParams;
  [Tool.dashboard]: ListDashboardsParams;
  [Tool.post]: ListPostsParams;
  [Tool.wiki]: ListWikisParams;
  [Tool.contact]: ListContactsParams;
};

/** The params the list's caller decides rather than the person filtering:
 *  where the list is, which page of it, and in what order. */
type NotAFilter =
  | "initiative_id"
  | "ids"
  | "page"
  | "page_size"
  | "sort_by"
  | "sort_dir"
  | "scope"
  | "slim"
  | "writable";

/** What a tool's list can be narrowed by. */
export type ToolListFilters<T extends Tool = Tool> = Omit<ToolListParams[T], NotAFilter>;

/** A tool list's filters as kept, with what has the wrong type dropped: a
 *  list of ids is numbers, everything else a switch, an id or a value. */
export const readToolListFilters = (raw: unknown): ToolListFilters => {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw).flatMap(([key, value]): [string, unknown][] => {
      if (Array.isArray(value)) {
        return [[key, value.filter((id) => typeof id === "number")]];
      }
      return typeof value === "string" ||
        typeof value === "boolean" ||
        (typeof value === "number" && Number.isFinite(value))
        ? [[key, value]]
        : [];
    })
  ) as ToolListFilters;
};

export type ToolFilterFieldsProps<T extends Tool = Tool> = {
  value: ToolListFilters<T>;
  onChange: (next: ToolListFilters<T>) => void;
  /** The initiative the list is in, whose definitions are the only properties
   *  it can be filtered by. Omitted on a list across initiatives. */
  initiativeId?: number;
  /** Controls only the page offers, in the same row as the shared fields. */
  children?: ReactNode;
};

type SearchTagFieldsProps = ToolFilterFieldsProps & {
  tool: Tool;
  /** Placeholder key in the tool's own namespace. */
  placeholder: string;
};

/** A search box, a tag picker and property conditions — what most tool lists
 *  narrow by. */
const SearchTagFields = ({
  tool,
  placeholder,
  value,
  onChange,
  initiativeId,
  children,
}: SearchTagFieldsProps) => {
  // The tool's own namespace is named after it, so the loose translate
  // signature rather than the statically-typed one.
  const { t: translate } = useTranslation([toolCamelPlural(tool) as FlatNamespace, "tags"]);
  const t = translate as TranslateFn;
  const id = useId();

  return (
    <>
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 md:flex-1">
          <Label
            htmlFor={`${id}-search`}
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.searchLabel")}
          </Label>
          <Input
            id={`${id}-search`}
            placeholder={t(placeholder)}
            value={value.search ?? ""}
            onChange={(event) => onChange({ ...value, search: event.target.value })}
            className="min-w-60"
          />
        </div>
        <div className="w-full space-y-2 sm:w-64">
          <Label htmlFor={`${id}-tags`} className="block font-medium text-muted-foreground text-xs">
            {t("tags:picker.filterLabel")}
          </Label>
          <TagFilterPicker
            id={`${id}-tags`}
            tagIds={value.tag_ids ?? []}
            onChange={(tagIds) => onChange({ ...value, tag_ids: tagIds })}
            placeholder={t("tags:picker.anyTag")}
          />
        </div>
        {children}
      </div>
      <PropertyFilterParam
        value={value.property_filters}
        onChange={(next) => onChange({ ...value, property_filters: next })}
        initiativeId={initiativeId}
      />
    </>
  );
};

/** "All" is a sentinel: the underlying filter is absent, not a value. */
const ALL_FILE_KINDS = "all";

/** The kinds a files list offers to narrow by: every one there is. */
const FILE_FILTER_KINDS = Object.values(FileKind);

/** A files list is also narrowed to one type of file. */
const FileFilterFields = ({
  value,
  onChange,
  initiativeId,
  children,
}: ToolFilterFieldsProps<typeof Tool.file>) => {
  const { t } = useTranslation("files");
  const id = useId();

  return (
    <SearchTagFields
      tool={Tool.file}
      placeholder="filters.searchFiles"
      value={value}
      onChange={onChange}
      initiativeId={initiativeId}
    >
      <div className="w-full space-y-2 sm:w-48">
        <Label htmlFor={`${id}-type`} className="block font-medium text-muted-foreground text-xs">
          {t("filters.type")}
        </Label>
        <Select
          value={value.kind ?? ALL_FILE_KINDS}
          onValueChange={(next) =>
            onChange({
              ...value,
              kind: next === ALL_FILE_KINDS ? undefined : (next as FileKind),
            })
          }
        >
          <SelectTrigger id={`${id}-type`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_FILE_KINDS}>{t("filters.allTypes")}</SelectItem>
            {FILE_FILTER_KINDS.map((kind) => (
              <SelectItem key={kind} value={kind}>
                {t(`filters.kinds.${kind}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {children}
    </SearchTagFields>
  );
};

/** A contacts list's kinds, each with the `is_organization` it sends. */
const CONTACT_KINDS = [
  { value: "all", isOrganization: undefined, label: "filters.allKinds" },
  { value: "people", isOrganization: false, label: "filters.people" },
  { value: "organizations", isOrganization: true, label: "filters.organizations" },
] as const;

/** A contacts list is also narrowed to people or to organizations. */
const ContactFilterFields = ({
  value,
  onChange,
  initiativeId,
  children,
}: ToolFilterFieldsProps<typeof Tool.contact>) => {
  const { t } = useTranslation("contacts");
  const id = useId();
  const kind = CONTACT_KINDS.find(
    (each) => each.isOrganization === (value.is_organization ?? undefined)
  );

  return (
    <SearchTagFields
      tool={Tool.contact}
      placeholder="filters.searchContacts"
      value={value}
      onChange={onChange}
      initiativeId={initiativeId}
    >
      <div className="w-full space-y-2 sm:w-48">
        <Label htmlFor={`${id}-kind`} className="block font-medium text-muted-foreground text-xs">
          {t("filters.kind")}
        </Label>
        <Select
          value={kind?.value}
          onValueChange={(next) =>
            onChange({
              ...value,
              is_organization: CONTACT_KINDS.find((each) => each.value === next)?.isOrganization,
            })
          }
        >
          <SelectTrigger id={`${id}-kind`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTACT_KINDS.map((each) => (
              <SelectItem key={each.value} value={each.value}>
                {t(each.label)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {children}
    </SearchTagFields>
  );
};

const searchAndTags = (tool: Tool, placeholder: string) => (props: ToolFilterFieldsProps) => (
  <SearchTagFields tool={tool} placeholder={placeholder} {...props} />
);

/** Every tool's filter fields. A mapped type over the tool enum, so a new tool
 *  has to say how its list is narrowed. */
const TOOL_FILTER_FIELDS: { [T in Tool]: ComponentType<ToolFilterFieldsProps<T>> } = {
  [Tool.project]: searchAndTags(Tool.project, "filters.searchProjects"),
  [Tool.file]: FileFilterFields,
  [Tool.counter_group]: searchAndTags(Tool.counter_group, "filters.searchGroups"),
  [Tool.calendar]: searchAndTags(Tool.calendar, "filters.searchCalendars"),
  [Tool.dashboard]: searchAndTags(Tool.dashboard, "filters.searchDashboards"),
  [Tool.post]: searchAndTags(Tool.post, "filters.searchPosts"),
  [Tool.wiki]: searchAndTags(Tool.wiki, "filters.searchWikis"),
  [Tool.contact]: ContactFilterFields,
};

/** A tool's filter fields, by tool. */
export const ToolFilterFields = <T extends Tool>({
  tool,
  ...props
}: ToolFilterFieldsProps<T> & { tool: T }) => {
  const Fields = TOOL_FILTER_FIELDS[tool] as ComponentType<ToolFilterFieldsProps<T>>;
  return <Fields {...props} />;
};

import { $insertNodeToNearestRoot } from "@lexical/utils";
import { $getNodeByKey, type LexicalEditor, type NodeKey } from "lexical";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  SearchEntityType,
  SearchSuggestion,
  SmartChipKind,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskSortPicker } from "@/components/layouts/TaskSortPicker";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useEditorInitiative } from "@/components/ui/editor/context/editor-initiative-context";
import {
  $createReferenceEmbedNode,
  $createTaskQueryEmbedNode,
  $isReferenceEmbedNode,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { SmartChipInsertDialog } from "@/components/ui/editor/plugins/smart-chip-insert-dialog";
import { SMART_CHIP_MENU } from "@/components/ui/editor/plugins/smart-chip-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAllProjects, useProjectTaskStatuses } from "@/hooks/useProjects";
import { NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import {
  CARD,
  type EmbedDisplay,
  type EmbedMode,
  emptyTaskQuery,
  ITEM_MODES,
  TASK_MODES,
  type TaskQuery,
} from "@/lib/embeds";
import { groupFields, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import { pluginFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { TASK_COLUMNS, taskFields } from "@/lib/layouts/tasks";
import { entityIcon } from "@/lib/searchResults";
import { chipKindsFor } from "@/lib/smartChips";

type Source = "item" | "tasks";

interface Item {
  entityType: SearchEntityType;
  entityId: number;
  title: string;
}

export interface EmbedDialogProps {
  activeEditor: LexicalEditor;
  onClose: () => void;
  /** The embed being changed. Absent, a new one is inserted. */
  nodeKey?: NodeKey;
}

/** What the dialog starts from: the embed being changed, or nothing yet. */
const readEmbed = (editor: LexicalEditor, nodeKey: NodeKey | undefined) =>
  nodeKey === undefined
    ? null
    : editor.getEditorState().read(() => {
        const node = $getNodeByKey(nodeKey);
        if (!$isReferenceEmbedNode(node)) return null;
        const query = node.getQuery();
        return {
          item: query
            ? null
            : {
                entityType: node.getEntityType(),
                entityId: node.getEntityId(),
                title: node.getTextContent(),
              },
          query,
          display: node.getDisplay(),
          label: node.getTextContent(),
        };
      });

/**
 * What an embed shows, chosen in two steps: where its content comes from —
 * one thing, or the tasks a filter matches in this page's initiative — and
 * how it is drawn. Opened to insert one, and from an embed's settings to
 * change it.
 */
export function EmbedDialog({ activeEditor, onClose, nodeKey }: EmbedDialogProps) {
  const { t } = useTranslation(["editor", "common"]);
  const initiativeId = useEditorInitiative();
  const start = useMemo(() => readEmbed(activeEditor, nodeKey), [activeEditor, nodeKey]);

  const [source, setSource] = useState<Source>(start?.query ? "tasks" : "item");
  const [item, setItem] = useState<Item | null>(start?.item ?? null);
  const [itemDisplay, setItemDisplay] = useState<EmbedDisplay>(
    start && !start.query ? start.display : CARD
  );
  const [query, setQuery] = useState<TaskQuery | null>(
    start?.query ?? (initiativeId ? emptyTaskQuery(initiativeId) : null)
  );
  const [taskDisplay, setTaskDisplay] = useState<EmbedDisplay>(
    start?.query ? start.display : { mode: "list" }
  );
  const [label, setLabel] = useState(start?.query ? start.label : "");

  const pick = (suggestion: SearchSuggestion) => {
    // The details chosen were facts about the last kind of thing.
    if (suggestion.entity_type !== item?.entityType) setItemDisplay(CARD);
    setItem({
      entityType: suggestion.entity_type,
      entityId: suggestion.entity_id,
      title: suggestion.title,
    });
  };

  const ready = source === "item" ? item !== null : query !== null;

  const save = () => {
    activeEditor.update(() => {
      const existing = nodeKey === undefined ? null : $getNodeByKey(nodeKey);
      const next =
        source === "tasks" && query
          ? $createTaskQueryEmbedNode(query, taskDisplay, label.trim())
          : item
            ? $createReferenceEmbedNode(item.entityType, item.entityId, item.title)
            : null;
      if (!next) return;
      if (source === "item") next.setShown(itemDisplay, null, item?.title ?? "");
      if ($isReferenceEmbedNode(existing)) {
        next.setCollapsed(existing.getCollapsed());
        existing.replace(next);
      } else {
        $insertNodeToNearestRoot(next);
      }
    });
    onClose();
  };

  return (
    <div className="space-y-4">
      <Tabs value={source} onValueChange={(value) => setSource(value as Source)}>
        <TabsList>
          <TabsTrigger value="item">{t("embeds.source.item")}</TabsTrigger>
          <TabsTrigger value="tasks" disabled={!initiativeId}>
            {t("embeds.source.tasks")}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {source === "item" ? (
        item ? (
          <ItemSettings
            item={item}
            display={itemDisplay}
            onDisplay={setItemDisplay}
            onChange={() => setItem(null)}
          />
        ) : (
          <SmartChipInsertDialog
            onPickEmbed={pick}
            initiativeId={initiativeId}
            activeEditor={activeEditor}
            onClose={onClose}
          />
        )
      ) : query ? (
        <TaskSettings
          query={query}
          onQuery={setQuery}
          display={taskDisplay}
          onDisplay={setTaskDisplay}
          label={label}
          onLabel={setLabel}
        />
      ) : (
        <p className="text-muted-foreground text-sm">{t("smartChips.noInitiative")}</p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          {t("common:cancel")}
        </Button>
        <Button type="button" onClick={save} disabled={!ready}>
          {nodeKey === undefined ? t("embeds.insert") : t("common:save")}
        </Button>
      </div>
    </div>
  );
}

/** The modes a source can draw as, as one row of choices. */
function ModePicker({
  modes,
  value,
  onChange,
}: {
  modes: EmbedMode[];
  value: EmbedMode;
  onChange: (mode: EmbedMode) => void;
}) {
  const { t } = useTranslation("editor");
  return (
    <div className="space-y-2">
      <Label className="block text-muted-foreground text-xs">{t("embeds.showAs")}</Label>
      <ToggleGroup
        type="single"
        variant="outline"
        value={value}
        onValueChange={(mode) => mode && onChange(mode as EmbedMode)}
        className="justify-start"
      >
        {modes.map((mode) => (
          <ToggleGroupItem key={mode} value={mode}>
            {t(`embeds.modes.${mode}` as never)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

/** A list of things to tick, each with its label. */
function Choices<T extends string>({
  options,
  chosen,
  onChange,
}: {
  options: { value: T; label: string }[];
  chosen: T[];
  onChange: (next: T[]) => void;
}) {
  return (
    <div className="grid grid-cols-fill-40/3 gap-2">
      {options.map((option) => (
        <Label key={option.value} className="flex items-center gap-2 font-normal">
          <Checkbox
            checked={chosen.includes(option.value)}
            onCheckedChange={(on) =>
              onChange(
                on ? [...chosen, option.value] : chosen.filter((value) => value !== option.value)
              )
            }
          />
          {option.label}
        </Label>
      ))}
    </div>
  );
}

function ItemSettings({
  item,
  display,
  onDisplay,
  onChange,
}: {
  item: Item;
  display: EmbedDisplay;
  onDisplay: (display: EmbedDisplay) => void;
  onChange: () => void;
}) {
  const { t } = useTranslation("editor");
  const facts = chipKindsFor(item.entityType);
  const Icon = entityIcon(item.entityType);
  // A kind with nothing to read about it has only its card to show.
  const modes = facts.length > 0 ? ITEM_MODES : ITEM_MODES.slice(0, 1);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-medium">{item.title}</span>
        <Button type="button" variant="ghost" size="sm" onClick={onChange}>
          {t("embeds.change")}
        </Button>
      </div>
      <ModePicker
        modes={modes}
        value={display.mode}
        onChange={(mode) =>
          onDisplay(mode === "fields" ? { mode, fields: display.fields ?? facts } : { mode })
        }
      />
      {display.mode === "fields" ? (
        <Choices<SmartChipKind>
          options={facts.map((kind) => ({
            value: kind,
            label: t(SMART_CHIP_MENU[kind].labelKey as never),
          }))}
          chosen={display.fields ?? []}
          onChange={(fields) => onDisplay({ mode: "fields", fields })}
        />
      ) : null}
    </div>
  );
}

const WHOLE_INITIATIVE = "initiative";

function TaskSettings({
  query,
  onQuery,
  display,
  onDisplay,
  label,
  onLabel,
}: {
  query: TaskQuery;
  onQuery: (query: TaskQuery) => void;
  display: EmbedDisplay;
  onDisplay: (display: EmbedDisplay) => void;
  label: string;
  onLabel: (label: string) => void;
}) {
  const { t, i18n } = useTranslation("editor");
  // Built-in fields are named in the layout's own namespaces, as a table's
  // header names them.
  const { t: fieldName } = useTranslation(LAYOUT_NAMESPACES);
  const { data: projects } = useAllProjects({ initiative_id: query.initiative_id });
  const { data: statuses = [] } = useProjectTaskStatuses(query.project_id);
  // One project's tasks can show its metadata too.
  const { data: definitions = NO_DEFINITIONS } = useOwnedDefinitions({
    initiativeId: query.initiative_id,
    owner: query.project_id === null ? undefined : { kind: "project", id: query.project_id },
  });
  const plugins = usePluginsOnItems(query.initiative_id);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="embed-label" className="block text-muted-foreground text-xs">
          {t("embeds.tasks.label")}
        </Label>
        <Input
          id="embed-label"
          value={label}
          onChange={(event) => onLabel(event.target.value)}
          placeholder={t("embeds.tasks.labelPlaceholder")}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="embed-tasks-from" className="block text-muted-foreground text-xs">
          {t("embeds.tasks.from")}
        </Label>
        <Select
          value={query.project_id === null ? WHOLE_INITIATIVE : String(query.project_id)}
          onValueChange={(value) =>
            onQuery({
              ...query,
              project_id: value === WHOLE_INITIATIVE ? null : Number(value),
              // A status belongs to one project, so a change of project clears them.
              filters: { ...query.filters, status_ids: [] },
            })
          }
        >
          <SelectTrigger id="embed-tasks-from">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={WHOLE_INITIATIVE}>{t("embeds.tasks.wholeInitiative")}</SelectItem>
            {(projects?.items ?? []).map((project) => (
              <SelectItem key={project.id} value={String(project.id)}>
                {project.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <TaskFilters
        scope={{
          kind: "project",
          memberScope: { type: "initiative", initiativeId: query.initiative_id },
          statuses: query.project_id === null ? [] : statuses,
          initiativeId: query.initiative_id,
          projectId: query.project_id ?? undefined,
        }}
        value={query.filters}
        onChange={(filters) => onQuery({ ...query, filters })}
        stacked
      />
      {display.mode === "count" ? null : (
        <TaskSortPicker
          value={query.sort[0] ?? null}
          onChange={(sort) => onQuery({ ...query, sort: sort ? [sort] : [] })}
          fields={fields}
        />
      )}
      <ModePicker
        modes={TASK_MODES}
        value={display.mode}
        onChange={(mode) =>
          onDisplay(mode === "table" ? { mode, columns: TASK_COLUMNS } : { mode })
        }
      />
      {display.mode === "table"
        ? // Each column under whose it is, as the layout editor lists fields.
          groupFields([...fields.values()]).map((group) => (
            <fieldset key={group.key} className="space-y-2">
              <legend className="mb-2 text-muted-foreground text-xs">
                {group.plugin === undefined ? fieldName(group.heading as never) : group.heading}
              </legend>
              <Choices
                options={group.fields.map((field) => ({
                  value: field.id,
                  label: field.source === "builtin" ? fieldName(field.label as never) : field.label,
                }))}
                chosen={display.columns ?? TASK_COLUMNS}
                onChange={(columns) => onDisplay({ mode: "table", columns })}
              />
            </fieldset>
          ))
        : null}
    </div>
  );
}

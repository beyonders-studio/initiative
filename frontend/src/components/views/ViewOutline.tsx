import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { EyeOff, FileText, GripVertical, LayoutList, Plus } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  TaskPageFieldId,
  type ToolViewWrite,
  type ViewDefinitionInput,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  addableFields,
  addablePluginParts,
  cardOf,
  columnsOf,
  dropInto,
  dropOn,
  HOLDERS,
  holdsPart,
  type NodePath,
  namedFields,
  pathKey,
  pathOf,
  removable,
  type Selection,
  sameSelection,
} from "@/lib/views/draft";
import { type FieldDef, VIEW_NAMESPACES } from "@/lib/views/fields";
import type { PluginOnItems } from "@/lib/views/plugins";
import { editsAField, PAGE_REGIONS, unplacedFields } from "@/lib/views/tasks";
import type { ViewNode } from "@/lib/views/tree";
import { localized } from "@/lib/widgets/widgetMeta";
import type { TranslateFn } from "@/types/i18n";

import type { ViewEdits } from "./ViewEditor";

/** A plug-in as the picker offers it: its name, and its parts by theirs. */
type PickerPlugin = {
  id: number;
  name: string;
  parts: { id: string; name: string; description?: string }[];
};

/** A part the picker offers beside the fields, under the group it names. */
type PickerPart = { group: "builtin" | "properties" | "layout"; label: string; node: ViewNode };

/** What Add offers where something is added: the fields, each plug-in's
 *  parts, and the other parts. */
export type AddChoices = { fields: FieldDef[]; plugins: PickerPlugin[]; parts: PickerPart[] };

/** What a pick in the Add picker does. */
export type Adders = {
  onField: (field: FieldDef) => void;
  onPart: (plugin: number, part: string) => void;
  onNode: (node: ViewNode) => void;
};

/** What a view can add: a card's fields and parts, or a table's columns. */
export const viewChoices = (
  definition: ViewDefinitionInput,
  fields: ReadonlyMap<string, FieldDef>,
  plugins: PickerPlugin[],
  translate: TranslateFn
): AddChoices => {
  const layout = definition.layout.type;
  if (layout === "calendar") return { fields: [], plugins: [], parts: [] };
  const card = cardOf(definition);
  const board = layout === "board";
  return {
    fields: addableFields(definition, fields),
    // A table draws fields only; a card takes parts as well.
    plugins: plugins.map((plugin) => ({
      ...plugin,
      parts: board ? addablePluginParts(card, plugin.id, plugin.parts) : [],
    })),
    parts: board
      ? [
          ...(holdsPart(card, "properties")
            ? []
            : [
                {
                  group: "properties" as const,
                  label: translate("viewEditor.allProperties"),
                  node: { type: "properties" },
                },
              ]),
          {
            group: "layout" as const,
            label: translate("viewEditor.group"),
            node: { type: "stack", props: { align: "start" }, children: [] },
          },
        ]
      : [],
  };
};

/** What a task's page can add: its fields not placed, its own parts once
 *  each, plug-in parts, sections and groups. */
export const pageChoices = (
  page: ViewNode,
  fields: ReadonlyMap<string, FieldDef>,
  plugins: PickerPlugin[],
  translate: TranslateFn
): AddChoices => {
  const named = namedFields(page);
  const pageFields = new Set<string>(Object.values(TaskPageFieldId));
  return {
    fields: [...fields.values()].filter(
      (field) =>
        !named.has(field.id) &&
        ((field.source === "builtin" && pageFields.has(field.id)) || field.source === "plugin")
    ),
    plugins: plugins.map((plugin) => ({
      ...plugin,
      parts: addablePluginParts(page, plugin.id, plugin.parts),
    })),
    parts: [
      ...PAGE_PARTS.filter((type) => !holdsPart(page, type)).map((type) => ({
        group: "builtin" as const,
        label: translate(`viewEditor.parts.${type}`),
        node: { type },
      })),
      ...(holdsPart(page, "properties")
        ? []
        : [
            {
              group: "properties" as const,
              label: translate("viewEditor.allProperties"),
              node: { type: "properties" },
            },
          ]),
      {
        group: "layout" as const,
        label: translate("viewEditor.section"),
        node: { type: "section", children: [] },
      },
      {
        group: "layout" as const,
        label: translate("viewEditor.group"),
        node: { type: "stack", children: [] },
      },
    ],
  };
};

/** The parts of a task's page that are its own, which it places at most once. */
const PAGE_PARTS = [
  "status",
  "dates",
  "comments",
  "relations",
  "case",
  "byline",
  "notice",
  "actions",
] as const;

/** Rows that stay where they are: an item page's regions. */
const FIXED = new Set<string>(PAGE_REGIONS);

const INTO = "into:";

const usePickerPlugins = (plugins: ReadonlyMap<number, PluginOnItems>): PickerPlugin[] => {
  const { i18n } = useTranslation();
  return [...plugins.values()].map((plugin) => ({
    id: plugin.id,
    name: plugin.name,
    parts: [...plugin.parts.values()].map((part) => ({
      id: part.id,
      name: localized(part.name, i18n.language) ?? part.id,
      description: localized(part.description, i18n.language),
    })),
  }));
};

/** What a part is called in the outline and the settings. */
export const usePartLabel = (
  fields: ReadonlyMap<string, FieldDef>,
  plugins: ReadonlyMap<number, PluginOnItems>
) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const pickerPlugins = usePickerPlugins(plugins);
  const labelOf = (field: FieldDef) =>
    field.source === "builtin" ? translate(field.label) : field.label;
  const partLabel = (node: ViewNode): string => {
    switch (node.type) {
      case "card":
        return translate("viewEditor.card");
      case "stack":
        return node.props?.direction === "row"
          ? translate("viewEditor.row")
          : translate("viewEditor.group");
      // An untitled section is told apart by what it starts with.
      case "section": {
        if (typeof node.props?.title === "string" && node.props.title) return node.props.title;
        const [first] = node.children ?? [];
        return first
          ? translate("viewEditor.sectionWith", { name: partLabel(first) })
          : translate("viewEditor.section");
      }
      case "properties":
        return translate("viewEditor.allProperties");
      case "plugin": {
        const plugin = pickerPlugins.find((each) => each.id === Number(node.props?.plugin));
        const part = plugin?.parts.find((each) => each.id === node.props?.part);
        return part?.name ?? translate("viewEditor.missingPart");
      }
      case "field": {
        const field = fields.get(String(node.props?.field));
        return field ? labelOf(field) : translate("viewEditor.missingField");
      }
      default:
        return translate(`viewEditor.parts.${node.type}`);
    }
  };
  return { labelOf, partLabel, pickerPlugins };
};

const useOutlineSensors = () =>
  useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

/**
 * What the view is made of, as a list beside the canvas: the view itself,
 * then a board's card part by part or a table's columns in order. A row is
 * dragged to move it, into another group as well, hidden from its own row,
 * and selected to change it. Add offers what is not there yet, under where it
 * comes from.
 */
export const ViewOutline = ({
  view,
  fields,
  plugins,
  choices,
  adders,
  selection,
  edits,
  locked,
}: {
  view: ToolViewWrite;
  fields: ReadonlyMap<string, FieldDef>;
  plugins: ReadonlyMap<number, PluginOnItems>;
  /** What Add offers, and what a pick does. */
  choices: AddChoices;
  adders: Adders;
  selection: Selection;
  edits: ViewEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
}) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const sensors = useOutlineSensors();
  const { labelOf, partLabel } = usePartLabel(fields, plugins);
  const { definition } = view;
  const layout = definition.layout.type;
  const card = cardOf(definition);
  const columns = columnsOf(definition);
  const isSelected = (other: Selection) => sameSelection(selection, other);

  const onColumnDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    edits.moveColumn(columns.indexOf(String(active.id)), columns.indexOf(String(over.id)));
  };

  return (
    <nav aria-label={translate("viewEditor.outline")} className="flex h-full flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        <OutlineRow
          id="view"
          depth={0}
          label={view.name}
          icon={<LayoutList className="h-4 w-4" aria-hidden="true" />}
          selected={isSelected({ kind: "view" })}
          onSelect={() => edits.select({ kind: "view" })}
          fixed
        />
        {layout === "board" ? (
          <>
            <OutlineRow
              id="card"
              depth={1}
              label={partLabel(card)}
              selected={isSelected({ kind: "part", path: [] })}
              onSelect={() => edits.select({ kind: "part", path: [] })}
              fixed
            />
            <PartTree
              root={card}
              depth={2}
              partLabel={partLabel}
              hideAction={(node) =>
                removable(node, fields)
                  ? translate("viewEditor.hide", { name: partLabel(node) })
                  : null
              }
              selection={selection}
              edits={edits}
              locked={locked}
            />
          </>
        ) : null}
        {layout === "table" ? (
          <DndContext sensors={sensors} onDragEnd={onColumnDragEnd}>
            <p className="px-2 pt-2 font-medium text-muted-foreground text-xs">
              {translate("viewEditor.columns")}
            </p>
            <SortableContext items={columns} strategy={verticalListSortingStrategy}>
              {columns.map((id) => {
                const field = fields.get(id);
                const label = field ? labelOf(field) : translate("viewEditor.missingField");
                return (
                  <OutlineRow
                    key={id}
                    id={id}
                    depth={1}
                    label={label}
                    selected={isSelected({ kind: "column", field: id })}
                    onSelect={() => edits.select({ kind: "column", field: id })}
                    // A table always has its title.
                    hide={
                      field?.hideable === false
                        ? undefined
                        : {
                            label: translate("viewEditor.hide", { name: label }),
                            run: () => edits.removeColumn(id),
                          }
                    }
                    locked={locked}
                  />
                );
              })}
            </SortableContext>
          </DndContext>
        ) : null}
      </div>
      {layout === "calendar" ? null : (
        <div className="border-t p-3">
          <AddPicker choices={choices} labelOf={labelOf} adders={adders} locked={locked} />
        </div>
      )}
    </nav>
  );
};

/**
 * A task's page as a list beside the canvas: the page, its header, main and
 * side with their parts, then the fields placed nowhere, which every task
 * still shows under More fields. A row is dragged to move it, into another
 * region or section as well; taking off a part that changes a field sends the
 * field to More fields.
 */
export const PageOutline = ({
  page,
  fields,
  plugins,
  choices,
  adders,
  selection,
  edits,
  locked,
}: {
  /** The page as one tree: the page, holding its header, main and side. */
  page: ViewNode;
  fields: ReadonlyMap<string, FieldDef>;
  plugins: ReadonlyMap<number, PluginOnItems>;
  choices: AddChoices;
  adders: Adders;
  selection: Selection;
  edits: ViewEdits;
  locked: boolean;
}) => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const translate = t as TranslateFn;
  const { labelOf, partLabel } = usePartLabel(fields, plugins);
  const regions = page.children ?? [];
  const unplaced = unplacedFields({
    header: regions[0]?.children ?? [],
    main: regions[1]?.children ?? [],
    side: regions[2]?.children ?? [],
  });
  return (
    <nav aria-label={translate("viewEditor.outline")} className="flex h-full flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        <OutlineRow
          id="view"
          depth={0}
          label={translate("viewEditor.taskPage")}
          icon={<FileText className="h-4 w-4" aria-hidden="true" />}
          selected={sameSelection(selection, { kind: "view" })}
          onSelect={() => edits.select({ kind: "view" })}
          fixed
        />
        <PartTree
          root={page}
          depth={1}
          partLabel={partLabel}
          hideAction={(node) =>
            FIXED.has(node.type) || !removable(node, fields)
              ? null
              : translate(editsAField(node) ? "viewEditor.toMoreFields" : "viewEditor.hide", {
                  name: partLabel(node),
                })
          }
          selection={selection}
          edits={edits}
          locked={locked}
        />
        {unplaced.length > 0 ? (
          <div className="pt-2">
            <p className="px-2 font-medium text-muted-foreground text-xs">
              {translate("tasks:edit.moreFields")}
            </p>
            <ul className="text-muted-foreground text-sm">
              {unplaced.map((node) => (
                <li key={`${node.type}:${String(node.props?.field ?? "")}`}>
                  <span className="block truncate py-1 pl-8">{partLabel(node)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <div className="border-t p-3">
        <AddPicker choices={choices} labelOf={labelOf} adders={adders} locked={locked} />
      </div>
    </nav>
  );
};

/**
 * A tree's parts as rows under its root, each group's below it. A row is
 * dragged onto another to take its place, in its own group or another, or
 * onto the slot at the end of a group, which each group shows while a row is
 * dragged (and an empty one always).
 */
const PartTree = ({
  root,
  depth,
  partLabel,
  hideAction,
  selection,
  edits,
  locked,
}: {
  root: ViewNode;
  depth: number;
  partLabel: (node: ViewNode) => string;
  /** What hiding the part is called, or null when it stays. */
  hideAction: (node: ViewNode) => string | null;
  selection: Selection;
  edits: ViewEdits;
  locked: boolean;
}) => {
  const sensors = useOutlineSensors();
  const [dragging, setDragging] = useState(false);

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(false);
    if (!over) return;
    const from = pathOf(String(active.id));
    const target = String(over.id);
    const to = target.startsWith(INTO)
      ? dropInto(root, from, pathOf(target.slice(INTO.length)))
      : dropOn(from, pathOf(target));
    if (to && pathKey(to) !== pathKey(from)) edits.movePart(from, to);
  };

  const rows = (parent: ViewNode, parentPath: NodePath, at: number): ReactNode => {
    const children = parent.children ?? [];
    const keys = children.map((_, index) => pathKey([...parentPath, index]));
    return (
      <SortableContext
        items={keys.filter((_, index) => !FIXED.has(children[index].type))}
        strategy={verticalListSortingStrategy}
      >
        {children.map((child, index) => {
          const path = [...parentPath, index];
          const hide = hideAction(child);
          return (
            <div key={keys[index]}>
              <OutlineRow
                id={keys[index]}
                depth={at}
                label={partLabel(child)}
                selected={sameSelection(selection, { kind: "part", path })}
                onSelect={() => edits.select({ kind: "part", path })}
                hide={hide ? { label: hide, run: () => edits.removePart(path) } : undefined}
                fixed={FIXED.has(child.type)}
                locked={locked}
              />
              {HOLDERS.has(child.type) ? (
                <>
                  {rows(child, path, at + 1)}
                  {dragging || !child.children?.length ? (
                    <EndSlot
                      id={`${INTO}${keys[index]}`}
                      depth={at + 1}
                      empty={!child.children?.length}
                    />
                  ) : null}
                </>
              ) : null}
            </div>
          );
        })}
      </SortableContext>
    );
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={() => setDragging(true)}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(false)}
    >
      {rows(root, [], depth)}
      {dragging && HOLDERS.has(root.type) ? (
        <EndSlot id={INTO} depth={depth} empty={false} />
      ) : null}
    </DndContext>
  );
};

/** Where a dragged row goes to the end of a group. */
const EndSlot = ({ id, depth, empty }: { id: string; depth: number; empty: boolean }) => {
  const { t } = useTranslation("projects");
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-md border border-transparent border-dashed py-1 pr-1 text-muted-foreground text-xs",
        isOver && "border-primary bg-muted"
      )}
      style={{ paddingLeft: `${depth * 0.75 + 1.75}rem` }}
    >
      {empty ? t("viewEditor.empty") : t("viewEditor.dropHere")}
    </div>
  );
};

const OutlineRow = ({
  id,
  depth,
  label,
  icon,
  selected,
  onSelect,
  hide,
  fixed = false,
  locked = false,
}: {
  id: string;
  depth: number;
  label: string;
  icon?: ReactNode;
  selected: boolean;
  onSelect: () => void;
  /** Absent: the row cannot be hidden. */
  hide?: { label: string; run: () => void };
  /** It has no place to move to. */
  fixed?: boolean;
  locked?: boolean;
}) => {
  const { t } = useTranslation("projects");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: fixed || locked,
  });
  return (
    <div
      ref={fixed ? undefined : setNodeRef}
      style={fixed ? undefined : { transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "group flex items-center gap-1 rounded-md pr-1 text-sm",
        selected ? "bg-accent text-accent-foreground" : "hover:bg-muted",
        isDragging && "opacity-60"
      )}
    >
      <span aria-hidden="true" style={{ width: `${depth * 0.75}rem` }} className="shrink-0" />
      {fixed ? (
        <span className="flex h-7 w-6 items-center justify-center text-muted-foreground">
          {icon}
        </span>
      ) : (
        <button
          type="button"
          className="flex h-7 w-6 cursor-grab items-center justify-center text-muted-foreground disabled:cursor-not-allowed"
          aria-label={t("viewEditor.move", { name: label })}
          disabled={locked}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        className="min-w-0 flex-1 truncate py-1 text-left"
        aria-pressed={selected}
        onClick={onSelect}
      >
        {label}
      </button>
      {hide ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
          aria-label={hide.label}
          disabled={locked}
          onClick={hide.run}
        >
          <EyeOff className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
};

type PickerGroupEntry = {
  key: string;
  heading: string;
  fields: FieldDef[];
  plugin: number;
  plugins: PickerPlugin["parts"];
  parts: PickerPart[];
};

/** What can be added, shown as things rather than ids: fields and parts by
 *  where they come from, each plug-in's under its name, and the layout
 *  parts. Opened from the outline's Add, or from a point on the canvas. */
export const AddPicker = ({
  choices: { fields, plugins, parts },
  labelOf,
  adders: { onField, onPart, onNode },
  locked,
  trigger,
  onOpenChange,
}: {
  choices: AddChoices;
  labelOf: (field: FieldDef) => string;
  adders: Adders;
  locked: boolean;
  /** In place of the outline's Add button. */
  trigger?: ReactNode;
  onOpenChange?: (open: boolean) => void;
}) => {
  const { t } = useTranslation("projects");
  const [open, setOpenState] = useState(false);
  const setOpen = (next: boolean) => {
    setOpenState(next);
    onOpenChange?.(next);
  };
  const own = (group: PickerPart["group"]) => parts.filter((part) => part.group === group);
  const groups: PickerGroupEntry[] = [
    {
      key: "builtin",
      heading: t("viewEditor.builtIn"),
      fields: fields.filter((field) => field.source === "builtin"),
      plugin: 0,
      plugins: [],
      parts: own("builtin"),
    },
    {
      key: "properties",
      heading: t("viewEditor.properties"),
      fields: fields.filter((field) => field.source === "property"),
      plugin: 0,
      plugins: [],
      parts: own("properties"),
    },
    ...plugins.map((plugin) => ({
      key: `plugin:${plugin.id}`,
      heading: plugin.name,
      fields: fields.filter((field) => field.plugin?.install === plugin.id),
      plugin: plugin.id,
      plugins: plugin.parts,
      parts: [],
    })),
    {
      key: "layout",
      heading: t("viewEditor.layoutParts"),
      fields: [],
      plugin: 0,
      plugins: [],
      parts: own("layout"),
    },
  ].filter((group) => group.fields.length + group.plugins.length + group.parts.length > 0);
  const pick = (run: () => void) => {
    run();
    setOpen(false);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={groups.length === 0 || locked}>
        {trigger ?? (
          <Button type="button" variant="outline" size="sm" className="w-full">
            <Plus className="h-4 w-4" />
            {t("viewEditor.add")}
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="max-h-96 w-72 overflow-y-auto p-2"
        aria-label={t("viewEditor.add")}
      >
        {groups.map((group) => (
          <PickerGroup key={group.key} heading={group.heading}>
            {group.parts.map((part) => (
              <PickerItem key={part.label} onClick={() => pick(() => onNode(part.node))}>
                {part.label}
              </PickerItem>
            ))}
            {group.fields.map((field) => {
              const Icon = field.icon;
              return (
                <PickerItem key={field.id} onClick={() => pick(() => onField(field))}>
                  {Icon ? (
                    <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  ) : null}
                  {labelOf(field)}
                </PickerItem>
              );
            })}
            {group.plugins.map((part) => (
              <PickerItem
                key={`part:${part.id}`}
                description={part.description}
                onClick={() => pick(() => onPart(group.plugin, part.id))}
              >
                {part.name}
              </PickerItem>
            ))}
          </PickerGroup>
        ))}
      </PopoverContent>
    </Popover>
  );
};

const PickerGroup = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <div className="py-1">
    <p className="px-2 pb-1 font-medium text-muted-foreground text-xs">{heading}</p>
    {children}
  </div>
);

const PickerItem = ({
  description,
  onClick,
  children,
}: {
  description?: string;
  onClick: () => void;
  children: ReactNode;
}) => (
  <button
    type="button"
    className="flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
    onClick={onClick}
  >
    <span className="flex items-center gap-2">{children}</span>
    {description ? <span className="text-muted-foreground text-xs">{description}</span> : null}
  </button>
);

import { useBlocker } from "@tanstack/react-router";
import { Laptop, Redo2, Smartphone, Tablet, Undo2, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ColumnLimit,
  DetailLayoutDefinitionInput,
  GetLayoutsParams,
  LayoutGrouping,
  LayoutPreset,
  ListLayoutDefinitionInput,
  ListLayoutReadKind,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import type { ScaleDisplay } from "@/components/properties/propertyHelpers";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { type MetadataOwner, NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import {
  detailLayoutOf,
  type LayoutChange,
  listLayouts,
  useSaveLayouts,
} from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { placedProperties, type StoredRegions, storedLayout } from "@/lib/layouts/detailLayout";
import {
  CARD_LISTS,
  cardOf,
  changeAt,
  columnsOf,
  dropAt,
  dropInto,
  HOLDERS,
  historyReducer,
  holdsPart,
  insertAt,
  LAYOUT_SELECTED,
  type ListLayout,
  type ListShape,
  moveNode,
  type NodePath,
  namedFields,
  nodeAt,
  type Place,
  pathAfterMove,
  pathAfterRemove,
  pathKey,
  type Selection,
  startHistory,
  withCard,
} from "@/lib/layouts/draft";
import { type FieldDef, propertyFieldId, withDisplays } from "@/lib/layouts/fields";
import {
  pluginFields,
  pluginKindOf,
  shippedPluginParts,
  usePluginsOnItems,
} from "@/lib/layouts/plugins";
import { taskFields } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";
import { toast } from "@/lib/mascotToast";
import type { TranslateFn } from "@/types/i18n";

import type { EditableDetail } from "./details";
import { CanvasFrame, type CanvasTools, LayoutCanvas, type PreviewWidth } from "./LayoutCanvas";
import {
  type Adders,
  AddPicker,
  DetailLayoutOutline,
  detailChoices,
  ListLayoutOutline,
  listChoices,
  PropertiesPartName,
  usePartLabel,
} from "./LayoutOutline";
import type { EditablePresets } from "./LayoutPresets";
import {
  DetailLayoutSettings,
  type LayoutProject,
  LayoutProperties,
  ListLayoutSettings,
} from "./LayoutSettingsPanel";

const noop = () => {};

/** No fields: where a list shows a property is its own card or columns, or
 *  its shape's, whatever plug-ins add. */
const NO_FIELDS: ReadonlyMap<string, FieldDef> = new Map();

/** What the part edits change while nothing is open. */
const EMPTY_TREE: LayoutNode = { type: "layout", children: [] };

const WIDTHS: { width: PreviewWidth; icon: typeof Laptop }[] = [
  { width: "desktop", icon: Laptop },
  { width: "tablet", icon: Tablet },
  { width: "phone", icon: Smartphone },
];

/** What can be done to the layout open in the editor. Each is one change to
 *  undo, and says what is selected after it. The part edits work on the open
 *  tree: a board's card, or the task's detail. */
export type LayoutEdits = {
  select: (selection: Selection) => void;
  /** The project opens on the open list. */
  makeDefault: () => void;
  /** Show the open list in the target's menu, or leave it out. */
  showList: (shown: boolean) => void;
  /** `to` is where the part is once moved. */
  movePart: (from: NodePath, to: NodePath) => void;
  removePart: (path: NodePath) => void;
  changePart: (path: NodePath, node: LayoutNode) => void;
  /** At `at`, or where the selection says. */
  addPart: (node: LayoutNode, at?: Place) => void;
  moveColumn: (from: number, to: number) => void;
  removeColumn: (field: string) => void;
  /** At `index`, or last. */
  addColumn: (field: string, index?: number) => void;
  /** The open list draws the scale `field` as `display`. */
  changeDisplay: (field: string, display: ScaleDisplay) => void;
  /** The open list offers `presets`, in order. */
  changePresets: (presets: LayoutPreset[]) => void;
  /** The open list offers `groupings`, in order, and starts grouped by
   *  `groupBy`, one of them, or not at all. */
  changeGroupings: (groupings: LayoutGrouping[], groupBy: string | null) => void;
  /** The open board limits these columns. */
  changeLimits: (limits: ColumnLimit[]) => void;
  /** The open layout goes back to the shipped one. */
  resetLayout: () => void;
};

/** What a target lists where that is not a project's tasks (a collection's
 *  files): the fields its lists can show, what they draw as shipped, and the
 *  open list drawn with the target's own items, its parts marked. */
export type EditableLists = {
  fields: ReadonlyMap<string, FieldDef>;
  shape: ListShape;
  /** `fields` as the open list draws them: its scales as it says. */
  preview: (layout: ListLayout, fields: ReadonlyMap<string, FieldDef>) => ReactNode;
  /** Whose metadata a field made in the editor may be: this collection's. */
  owner?: MetadataOwner;
  /** What a list is, as a key: what its settings say of it. */
  help: (kind: ListLayoutReadKind) => string;
};

/** What the editor knows a detail by: its kind, and for a page laid out per
 *  type of item, its type (`task:12`). What `initialKind` names. */
const detailKey = ({ spec, taskTypeId }: EditableDetail): string =>
  taskTypeId ? `${spec.kind}:${taskTypeId}` : spec.kind;

/** What the editor changes: each list's layout and each detail's (null: drawn
 *  as shipped), by {@link detailKey}, and the list the target opens on. Save
 *  stores only what changed, each on its own. */
type Draft = {
  lists: Partial<Record<ListLayoutReadKind, ListLayoutDefinitionInput | null>>;
  details: Partial<Record<string, DetailLayoutDefinitionInput | null>>;
  opensOn: ListLayoutReadKind;
};

const draftOf = (set: ToolLayoutSetRead, details: EditableDetail[]): Draft => {
  const lists = listLayouts(set);
  return {
    lists: Object.fromEntries(
      lists.map((layout) => [
        layout.kind,
        layout.updated_at ? (layout.definition as ListLayoutDefinitionInput) : null,
      ])
    ),
    details: Object.fromEntries(
      details.map((detail) => [
        detailKey(detail),
        detailLayoutOf(set, detail.spec.kind, detail.taskTypeId),
      ])
    ),
    opensOn: lists.find((layout) => layout.is_default)?.kind ?? "board",
  };
};

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** What a save sends to make `base` into `draft`: each layout that changed,
 *  saved or put back as shipped, then the list it opens on, if that moved. */
const changesFrom = (base: Draft, draft: Draft, details: EditableDetail[]): LayoutChange[] => {
  const changes: LayoutChange[] = [];
  for (const [kind, definition] of Object.entries(draft.lists) as [
    ListLayoutReadKind,
    ListLayoutDefinitionInput | null,
  ][]) {
    if (same(definition, base.lists[kind])) continue;
    changes.push(definition ? { save: { kind, definition } } : { reset: kind });
  }
  for (const detail of details) {
    const key = detailKey(detail);
    const definition = draft.details[key] ?? null;
    if (same(definition, base.details[key] ?? null)) continue;
    const { kind } = detail.spec;
    const taskTypeId = detail.taskTypeId;
    changes.push(
      definition
        ? { save: { kind, ...(taskTypeId ? { task_type_id: taskTypeId } : {}), definition } }
        : { reset: kind, ...(taskTypeId ? { taskTypeId } : {}) }
    );
  }
  if (draft.opensOn !== base.opensOn) changes.push({ opensOn: draft.opensOn });
  return changes;
};

/** Where a part is put when it is added: into the group (or region) that is
 *  selected, after the part that is, or at the end of `fallback`. */
const placeFor = (
  tree: LayoutNode,
  selection: Selection,
  fallback: NodePath
): { parent: NodePath; index: number } => {
  const end = { parent: fallback, index: nodeAt(tree, fallback)?.children?.length ?? 0 };
  if (selection.kind !== "part") return end;
  const node = nodeAt(tree, selection.path);
  if (!node || selection.path.length === 0) return end;
  if (HOLDERS.has(node.type)) {
    return { parent: selection.path, index: node.children?.length ?? 0 };
  }
  return { parent: selection.path.slice(0, -1), index: (selection.path.at(-1) ?? 0) + 1 };
};

/** Whether a selection still names something in what is open, as an undo may
 *  take away what was selected. */
const stillThere = (selection: Selection, tree: LayoutNode, columns: string[]): boolean => {
  if (selection.kind === "part") return nodeAt(tree, selection.path) !== undefined;
  if (selection.kind === "column") return columns.includes(selection.field);
  return true;
};

/**
 * A target's layouts, edited where they are seen: a project's table, board and
 * calendar and its task's detail, or the initiative calendar's event detail.
 * It takes the whole screen: which layout is open and what can be done across
 * the top, the outline of it on the left, it drawn with the target's own in
 * the middle, and the settings of what is selected on the right.
 *
 * Every change is a draft until Save, which stores each layout that changed on
 * its own, so the others keep their dates; readers see the saved layouts until
 * then. Nothing changes while a save is under way, and leaving with changes,
 * or during a save, asks first.
 */
export const LayoutEditor = ({
  target,
  initiativeId,
  project,
  lists,
  details,
  presets,
  set,
  initialKind,
  ownPropertiesEditable = false,
  onClose,
}: {
  target: GetLayoutsParams;
  initiativeId: number;
  /** The project whose lists these are, drawn with its tasks. A target with
   *  no project offers its lists' presets alone, or draws its `lists`. */
  project?: LayoutProject;
  lists?: EditableLists;
  details: EditableDetail[];
  /** The presets its lists offer; a target with no lists has none. */
  presets?: EditablePresets;
  /** The target's layouts, read by someone who may change them. */
  set: ToolLayoutSetRead;
  /** The layout to open on: a list's kind, or the task's detail. */
  initialKind?: string;
  /** Whether the request may make, edit and delete the target's own
   *  properties, the project's or the collection's: the server's answer on
   *  it. Without it the panel lists them and changes nothing. */
  ownPropertiesEditable?: boolean;
  onClose: () => void;
}) => {
  const { t, i18n } = useTranslation(["projects", "layouts", "common"]);
  const translate = t as TranslateFn;
  const wide = atLeast(useWidthClass(), "md");
  const [base, setBase] = useState(() => draftOf(set, details));
  const [history, dispatch] = useReducer(historyReducer<Draft>, base, startHistory<Draft>);
  const draft = history.present;
  const kinds = listLayouts(set).map((layout) => layout.kind);
  const offered = [...kinds, ...details.map(detailKey)];
  const [active, setActive] = useState<string>(
    initialKind && offered.includes(initialKind as ListLayoutReadKind)
      ? initialKind
      : project || lists
        ? draft.opensOn
        : details[0]
          ? detailKey(details[0])
          : ""
  );
  const [selected, setSelected] = useState<Selection>(LAYOUT_SELECTED);
  const openDetail = details.find((detail) => detailKey(detail) === active);
  const onDetail = openDetail !== undefined;
  const current: ListLayout | null = onDetail
    ? null
    : {
        kind: active as ListLayoutReadKind,
        definition: draft.lists[active as ListLayoutReadKind] ?? {},
        shape: lists?.shape,
      };
  const stored = openDetail ? (draft.details[detailKey(openDetail)] ?? null) : null;
  // The plug-ins that draw on what is open: a list's tasks, or a detail's item.
  const plugins = usePluginsOnItems(
    initiativeId,
    !lists,
    openDetail ? pluginKindOf(openDetail.spec.kind) : "task"
  );
  const detail = useMemo(
    () =>
      openDetail
        ? openDetail.spec.root(stored as StoredRegions | null, shippedPluginParts(plugins))
        : null,
    [openDetail, stored, plugins]
  );
  const [width, setWidth] = useState<PreviewWidth>("desktop");
  const dirty = !same(draft, base);

  const save = useSaveLayouts(target);
  const saving = save.isPending;

  // Someone else's change, read while nothing is changed here, is what the
  // editor starts from. One read mid-edit is set aside: Save sends only what
  // this editor changed, against what it started from.
  const adopt = (stored: ToolLayoutSetRead) => {
    const fresh = draftOf(stored, details);
    setSeen(stored);
    setBase(fresh);
    dispatch({ type: "reset", present: fresh });
  };
  const [seen, setSeen] = useState(set);
  if (seen !== set && !saving) {
    setSeen(set);
    if (!dirty) adopt(set);
  }

  // The owner whose metadata its fields may be: a project's tasks', or a
  // collection's files'.
  const owner: MetadataOwner | undefined =
    lists?.owner ?? (project ? { kind: "project", id: project.id } : undefined);
  const { data: definitions = NO_DEFINITIONS } = useOwnedDefinitions({
    initiativeId,
    owner: project ? owner : undefined,
  });
  // A detail's fields are its own; a list's are its target's.
  const fields = useMemo(
    () =>
      (!openDetail && lists?.fields) ||
      (openDetail?.fields ?? taskFields)(definitions, pluginFields(plugins, i18n.language)),
    [lists, openDetail, definitions, plugins, i18n.language]
  );
  // The tree the part edits change.
  const tree = current ? cardOf(current.definition, fields, current.shape) : (detail ?? EMPTY_TREE);
  const columns = current ? columnsOf(current.definition, fields, current.shape) : [];
  const selection = stillThere(selected, tree, columns) ? selected : LAYOUT_SELECTED;

  // Which lists the target's menu offers, as the draft has them: each its own
  // layout does not hide. A project shows one at least.
  const hiddenOf = (kind: ListLayoutReadKind, lists: Draft["lists"] = draft.lists) =>
    lists[kind]?.hidden ?? false;
  const shownKinds = kinds.filter((kind) => !hiddenOf(kind));
  /** `lists`, with the list it opens on moved to the first shown where the one
   *  it was on is not. */
  const withLists = (lists: Draft["lists"]): Draft => {
    const shown = kinds.filter((kind) => !hiddenOf(kind, lists));
    const opensOn = shown.includes(draft.opensOn) ? draft.opensOn : (shown[0] ?? draft.opensOn);
    return { ...draft, lists, opensOn };
  };

  /** The names of the layouts that show the property, as the draft has
   *  them: each shown list, and each page, that places it or shows every
   *  property. */
  const shownOn = (propertyId: number): string[] => {
    const field = propertyFieldId(propertyId);
    const onLists = shownKinds.filter((kind) => {
      const definition = draft.lists[kind] ?? {};
      if (kind === "table") return columnsOf(definition, NO_FIELDS, lists?.shape).includes(field);
      if (!CARD_LISTS.has(kind)) return false;
      const card = cardOf(definition, NO_FIELDS, lists?.shape);
      return namedFields(card).has(field) || holdsPart(card, "properties");
    });
    const onPages = details.filter((each) => {
      const page = each.spec.root(draft.details[detailKey(each)] as StoredRegions | null);
      return placedProperties(page).has(propertyId) || holdsPart(page, "properties");
    });
    return [
      ...onLists.map((kind) => translate(listLayoutLooks[kind].labelKey)),
      ...onPages.map((each) => translate(each.words.name, { name: each.typeName })),
    ];
  };
  // The target's own properties, managed beside the layout they are placed on.
  const properties =
    owner && selection.kind === "layout" ? (
      <LayoutProperties
        initiativeId={initiativeId}
        owner={owner}
        canManage={ownPropertiesEditable}
        shownOn={shownOn}
      />
    ) : null;

  const changeDraft = (next: Draft, then?: Selection) => {
    if (saving) return;
    dispatch({ type: "change", present: next });
    if (then) setSelected(then);
  };
  const changeList = (definition: ListLayoutDefinitionInput, then?: Selection) => {
    if (current) {
      changeDraft({ ...draft, lists: { ...draft.lists, [current.kind]: definition } }, then);
    }
  };
  const changeDetail = (layout: DetailLayoutDefinitionInput | null, then?: Selection) => {
    if (openDetail) {
      changeDraft(
        { ...draft, details: { ...draft.details, [detailKey(openDetail)]: layout } },
        then
      );
    }
  };
  /** The open tree, changed: a board's card, or the detail, which is then the
   *  target's own. */
  const changeTree = (next: LayoutNode, then?: Selection) => {
    if (current) changeList(withCard(current.definition, next), then);
    else changeDetail(storedLayout(next), then);
  };

  const edits: LayoutEdits = {
    select: setSelected,
    makeDefault: () => {
      if (current) changeDraft({ ...draft, opensOn: current.kind });
    },
    showList: (shown) => {
      if (!current) return;
      changeDraft(
        withLists({ ...draft.lists, [current.kind]: { ...current.definition, hidden: !shown } })
      );
    },
    movePart: (from, to) => {
      changeTree(
        moveNode(tree, from, to),
        selection.kind === "part"
          ? { kind: "part", path: pathAfterMove(selection.path, from, to) }
          : selection
      );
    },
    removePart: (path) => {
      const after = selection.kind === "part" ? pathAfterRemove(selection.path, path) : null;
      changeTree(
        changeAt(tree, path, () => null),
        { kind: "part", path: after ?? path.slice(0, -1) }
      );
    },
    changePart: (path, node) => changeTree(changeAt(tree, path, () => node)),
    addPart: (node, at) => {
      // A detail takes what is added into its main column; a card at its end.
      const { parent, index } = at ?? placeFor(tree, selection, onDetail ? [1] : []);
      // What was added is selected, to change it at once.
      changeTree(insertAt(tree, parent, node, index), {
        kind: "part",
        path: [...parent, index],
      });
    },
    resetLayout: () =>
      current
        ? changeDraft(withLists({ ...draft.lists, [current.kind]: null }), LAYOUT_SELECTED)
        : changeDetail(null, LAYOUT_SELECTED),
    moveColumn: (from, to) => {
      if (!current) return;
      const next = [...columns];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      changeList({ ...current.definition, columns: next });
    },
    removeColumn: (field) => {
      if (!current) return;
      changeList(
        { ...current.definition, columns: columns.filter((each) => each !== field) },
        LAYOUT_SELECTED
      );
    },
    addColumn: (field, index) => {
      if (!current) return;
      const next = [...columns];
      next.splice(index ?? next.length, 0, field);
      changeList({ ...current.definition, columns: next }, { kind: "column", field });
    },
    changeDisplay: (field, display) => {
      if (!current) return;
      changeList({
        ...current.definition,
        displays: { ...current.definition.displays, [field]: display },
      });
    },
    changePresets: (presets) => {
      if (current) changeList({ ...current.definition, presets });
    },
    changeGroupings: (groupings, groupBy) => {
      if (current) changeList({ ...current.definition, groupings, group_by: groupBy });
    },
    changeLimits: (limits) => {
      if (current) changeList({ ...current.definition, limits });
    },
  };

  // What Add offers, in the outline and at a point on the canvas, and what a
  // pick does there.
  // Where the target has properties of its own, the part showing every
  // property shows the initiative's metadata as well.
  const propertiesPart = owner ? "layouts:allPropertiesAndMetadata" : "layouts:allMetadata";
  const { labelOf, partLabel, pickerPlugins } = usePartLabel(
    fields,
    plugins,
    openDetail?.words.parts,
    propertiesPart
  );
  const listed = current
    ? listChoices(current, fields, pickerPlugins, translate, propertiesPart)
    : detail && openDetail
      ? detailChoices(detail, openDetail, fields, pickerPlugins, translate, propertiesPart)
      : { fields: [], plugins: [], parts: [] };
  // Wherever a field can be placed, a new one can be made, placed where Add
  // was opened: the owner's metadata, or a property of the initiative's.
  const choices =
    current?.kind === "calendar" || current?.kind === "gantt" || (!current && !detail)
      ? listed
      : { ...listed, newField: { initiativeId, owner } };
  const addersAt = (place?: Place): Adders =>
    current?.kind === "table"
      ? { onField: (id) => edits.addColumn(id, place?.index), onPart: noop, onNode: noop }
      : {
          onField: (id) => edits.addPart({ type: "field", props: { field: id } }, place),
          onPart: (plugin, part) =>
            edits.addPart({ type: "plugin", props: { plugin, part } }, place),
          onNode: (node) => edits.addPart(node, place),
        };
  // The regions of a detail, and a card itself, stay where they are.
  const fixedDepth = onDetail ? 1 : 0;
  const holds = (of: Selection) =>
    of.kind === "part" && HOLDERS.has(nodeAt(tree, of.path)?.type ?? "");
  const tools: CanvasTools = {
    locked: saving,
    revision: draft,
    knows: (of) =>
      of.kind === "column"
        ? columns.includes(of.field)
        : of.kind === "part" &&
          nodeAt(tree, of.path) !== undefined &&
          // The detail itself is the outline's top row, not a part.
          !(onDetail && of.path.length === 0),
    inside: (of) => {
      const node = of.kind === "part" ? nodeAt(tree, of.path) : undefined;
      return of.kind === "part" && node && HOLDERS.has(node.type) && !node.children?.length
        ? { parent: of.path, index: 0 }
        : null;
    },
    nameOf: (of) => {
      if (of.kind === "column") {
        const field = fields.get(of.field);
        return field ? labelOf(field) : "";
      }
      const node = of.kind === "part" ? nodeAt(tree, of.path) : undefined;
      return node ? partLabel(node) : "";
    },
    around: (of) => {
      if (of.kind === "column") {
        const index = columns.indexOf(of.field);
        return index < 0
          ? null
          : {
              before: { parent: [], index },
              after: { parent: [], index: index + 1 },
              across: true,
            };
      }
      if (of.kind !== "part" || of.path.length <= fixedDepth) return null;
      const parent = of.path.slice(0, -1);
      const index = of.path.at(-1) ?? 0;
      const holder = nodeAt(tree, parent);
      return {
        before: { parent, index },
        after: { parent, index: index + 1 },
        across: holder?.type === "stack" && holder.props?.direction === "row",
      };
    },
    holds,
    movable: (of) => of.kind === "column" || (of.kind === "part" && of.path.length > fixedDepth),
    move: (from, over, after) => {
      if (from.kind === "column" && over.kind === "column") {
        const at = columns.indexOf(from.field);
        let to = columns.indexOf(over.field) + (after ? 1 : 0);
        if (at < to) to -= 1;
        if (at >= 0 && to !== at) edits.moveColumn(at, to);
        return;
      }
      if (from.kind !== "part" || over.kind !== "part") return;
      // Onto a group, it goes last in it; beside a part, before or after it.
      const to = holds(over)
        ? dropInto(tree, from.path, over.path)
        : over.path.length > 0
          ? dropAt(from.path, over.path.slice(0, -1), (over.path.at(-1) ?? 0) + (after ? 1 : 0))
          : null;
      if (to && pathKey(to) !== pathKey(from.path)) edits.movePart(from.path, to);
    },
    addAt: (place, trigger, onOpenChange) => (
      <AddPicker
        choices={choices}
        labelOf={labelOf}
        adders={addersAt(place)}
        locked={saving}
        trigger={trigger}
        onOpenChange={onOpenChange}
      />
    ),
  };

  const commit = () =>
    save.mutate(changesFrom(base, draft, details), {
      onSuccess: (stored) => {
        if (stored) adopt(stored);
        toast.success(t("layouts:saved"));
      },
    });

  // Leaving on purpose (Close after the question) passes.
  const leaving = useRef(false);
  const blocker = useBlocker({
    shouldBlockFn: () => (dirty || saving) && !leaving.current,
    enableBeforeUnload: () => (dirty || saving) && !leaving.current,
    withResolver: true,
  });
  const [asking, setAsking] = useState(false);
  const close = () => {
    if (dirty || saving) setAsking(true);
    else onClose();
  };

  // The keys people already reach for: undo and redo, wherever focus is but
  // a text field, which keeps its own, and never while a save is under way.
  const savingRef = useRef(saving);
  savingRef.current = saving;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (!savingRef.current) dispatch({ type: event.shiftKey ? "redo" : "undo" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <PropertiesPartName.Provider value={propertiesPart}>
      <div
        className="fixed inset-0 z-50 flex flex-col bg-background"
        role="dialog"
        aria-modal="true"
        aria-label={t("layouts:title")}
      >
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("layouts:close")}
            onClick={close}
          >
            <X className="h-4 w-4" />
          </Button>
          <Select
            value={active}
            disabled={!wide}
            onValueChange={(value) => {
              setActive(value);
              setSelected(LAYOUT_SELECTED);
            }}
          >
            <SelectTrigger className="w-56" aria-label={t("layouts:layout")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {kinds.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {hiddenOf(kind)
                    ? t("layouts:hiddenList", { name: translate(listLayoutLooks[kind].labelKey) })
                    : translate(listLayoutLooks[kind].labelKey)}
                </SelectItem>
              ))}
              {kinds.length > 0 ? <SelectSeparator /> : null}
              {details.map((detail) => (
                <SelectItem key={detailKey(detail)} value={detailKey(detail)}>
                  {translate(detail.words.name, { name: detail.typeName })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex-1" />
          <ToggleGroup
            type="single"
            value={width}
            onValueChange={(next) => next && setWidth(next as PreviewWidth)}
            aria-label={t("layouts:previewWidth")}
            disabled={!wide}
          >
            {WIDTHS.map(({ width: each, icon: Icon }) => (
              <ToggleGroupItem
                key={each}
                value={each}
                aria-label={t(`layouts:width.${each}`)}
                className="h-8 w-8"
              >
                <Icon className="h-4 w-4" />
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("layouts:undo")}
            disabled={saving || history.past.length === 0}
            onClick={() => dispatch({ type: "undo" })}
          >
            <Undo2 className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("layouts:redo")}
            disabled={saving || history.future.length === 0}
            onClick={() => dispatch({ type: "redo" })}
          >
            <Redo2 className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!dirty || saving}
            onClick={() => {
              dispatch({ type: "reset", present: base });
              setSelected(LAYOUT_SELECTED);
            }}
          >
            {t("layouts:discard")}
          </Button>
          <Button type="button" size="sm" disabled={!dirty || saving} onClick={commit}>
            {saving ? t("layouts:saving") : t("common:save")}
          </Button>
        </header>
        {/* A screen too narrow to edit on keeps the draft, and says so. */}
        {!wide ? (
          <p className="p-6 text-muted-foreground text-sm">{t("layouts:compact")}</p>
        ) : current && ((project && presets) || lists) ? (
          <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
            <aside className="min-h-0 border-r">
              <ListLayoutOutline
                layout={current}
                fields={fields}
                plugins={plugins}
                choices={choices}
                adders={addersAt()}
                selection={selection}
                edits={edits}
                locked={saving}
              />
            </aside>
            <main className="min-h-0">
              {project ? (
                <LayoutCanvas
                  projectId={project.id}
                  initiativeId={project.initiativeId}
                  statuses={project.statuses}
                  layout={current}
                  fields={fields}
                  width={width}
                  selection={selection}
                  onSelect={setSelected}
                  tools={tools}
                  onGroupingsChange={(groupings) =>
                    edits.changeGroupings(groupings, current.definition.group_by ?? null)
                  }
                />
              ) : lists ? (
                <CanvasFrame
                  width={width}
                  selection={selection}
                  onSelect={setSelected}
                  tools={tools}
                >
                  {lists.preview(current, withDisplays(fields, current.definition.displays))}
                </CanvasFrame>
              ) : null}
            </main>
            <aside className="min-h-0 overflow-y-auto border-l">
              <ListLayoutSettings
                layout={current}
                presets={presets}
                help={lists ? lists.help(current.kind) : `layouts:listHelp.${current.kind}`}
                opensFirst={draft.opensOn === current.kind}
                shown={{
                  value: !hiddenOf(current.kind),
                  canHide: shownKinds.some((kind) => kind !== current.kind),
                }}
                stored={draft.lists[current.kind] != null}
                fields={fields}
                statuses={project?.statuses}
                selection={selection}
                edits={edits}
                locked={saving}
              />
              {properties}
            </aside>
          </div>
        ) : current && presets ? (
          // A list with nothing of its own to draw here (the calendar's events
          // and tasks): its settings, which are its presets.
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-xl">
              <ListLayoutSettings
                layout={current}
                presets={presets}
                help="layouts:calendarListHelp"
                stored={draft.lists[current.kind] != null}
                fields={fields}
                selection={LAYOUT_SELECTED}
                edits={edits}
                locked={saving}
              />
            </div>
          </div>
        ) : detail && openDetail ? (
          <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
            <aside className="min-h-0 border-r">
              <DetailLayoutOutline
                detail={detail}
                of={openDetail}
                fields={fields}
                plugins={plugins}
                choices={choices}
                adders={addersAt()}
                selection={selection}
                edits={edits}
                locked={saving}
              />
            </aside>
            <main className="min-h-0">
              <CanvasFrame width={width} selection={selection} onSelect={setSelected} tools={tools}>
                {openDetail.preview(detail)}
              </CanvasFrame>
            </main>
            <aside className="min-h-0 overflow-y-auto border-l">
              <DetailLayoutSettings
                detail={detail}
                of={openDetail}
                stored={stored !== null}
                fields={fields}
                selection={selection}
                edits={edits}
                locked={saving}
              />
              {properties}
            </aside>
          </div>
        ) : null}
        <ConfirmDialog
          open={asking || blocker.status === "blocked"}
          onOpenChange={(open) => {
            if (open) return;
            setAsking(false);
            blocker.reset?.();
          }}
          title={t("layouts:unsavedTitle")}
          description={t(saving ? "layouts:savingBody" : "layouts:unsavedBody")}
          confirmLabel={t("layouts:leave")}
          cancelLabel={t("layouts:stay")}
          onConfirm={() => {
            leaving.current = true;
            setAsking(false);
            if (blocker.status === "blocked") blocker.proceed?.();
            else onClose();
          }}
          destructive
        />
      </div>
    </PropertiesPartName.Provider>
  );
};

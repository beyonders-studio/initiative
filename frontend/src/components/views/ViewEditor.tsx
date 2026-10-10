import { useBlocker } from "@tanstack/react-router";
import {
  Copy,
  Laptop,
  MoreHorizontal,
  Plus,
  Redo2,
  Smartphone,
  Tablet,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ItemLayoutDefinitionInput,
  TaskStatusRead,
  ToolViewSetRead,
  ToolViewWrite,
  ViewDefinitionInput,
} from "@/api/generated/initiativeAPI.schemas";
import { viewName } from "@/components/projects/projectTasksConfig";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { taskPageOf, usePutProjectViews, viewSetWrite, viewWrites } from "@/hooks/useProjectViews";
import { useProperties } from "@/hooks/useProperties";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { toast } from "@/lib/mascotToast";
import {
  cardOf,
  changeAt,
  columnsOf,
  dropAt,
  dropInto,
  HOLDERS,
  historyReducer,
  insertAt,
  MAX_NAME_LENGTH,
  MAX_VIEWS,
  moveNode,
  type NodePath,
  nodeAt,
  type Place,
  pathAfterMove,
  pathAfterRemove,
  pathKey,
  type Selection,
  startHistory,
  VIEW_SELECTED,
  withCard,
} from "@/lib/views/draft";
import { pluginFields, usePluginsOnItems } from "@/lib/views/plugins";
import { type StoredRegions, storedLayout, taskFields, taskPageRoot } from "@/lib/views/tasks";
import type { ViewNode } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

import { type CanvasTools, PageCanvas, type PreviewWidth, ViewCanvas } from "./ViewCanvas";
import {
  type Adders,
  AddPicker,
  PageOutline,
  pageChoices,
  usePartLabel,
  ViewOutline,
  viewChoices,
} from "./ViewOutline";
import { PageSettingsPanel, ViewSettingsPanel } from "./ViewSettingsPanel";

const noop = () => {};

const WIDTHS: { width: PreviewWidth; icon: typeof Laptop }[] = [
  { width: "desktop", icon: Laptop },
  { width: "tablet", icon: Tablet },
  { width: "phone", icon: Smartphone },
];

/** What can be done to what is open in the editor. Each is one change to
 *  undo, and says what is selected after it. The part edits work on the open
 *  tree: a board's card, or the task page. */
export type ViewEdits = {
  select: (selection: Selection) => void;
  setDefinition: (definition: ViewDefinitionInput) => void;
  rename: (name: string) => void;
  makeDefault: () => void;
  /** `to` is where the part is once moved. */
  movePart: (from: NodePath, to: NodePath) => void;
  removePart: (path: NodePath) => void;
  changePart: (path: NodePath, node: ViewNode) => void;
  /** At `at`, or where the selection says. */
  addPart: (node: ViewNode, at?: Place) => void;
  moveColumn: (from: number, to: number) => void;
  removeColumn: (field: string) => void;
  /** At `index`, or last. */
  addColumn: (field: string, index?: number) => void;
  /** The task page goes back to the shipped one. */
  resetPage: () => void;
};

/** The task page, in the editor's list beside the views. A slug has no colon,
 *  so no view is named this. */
export const TASK_PAGE = "page:task";

/** A view in the editor, named by a key of the editor's own: its slug once
 *  saved, and `new:<n>` until then, as the server names a new view. */
type DraftView = ToolViewWrite & { key: string };

/** What the editor changes: the views, and the task page's layout (null: the
 *  shipped page). One Save stores both. */
type Draft = { views: DraftView[]; page: ItemLayoutDefinitionInput | null };

const draftOf = (set: ToolViewSetRead): Draft => ({
  views: viewWrites(set).map((view) => ({ ...view, key: view.slug ?? "" })),
  page: taskPageOf(set),
});

/** Where a part is put when it is added: into the group (or region) that is
 *  selected, after the part that is, or at the end of `fallback`. */
const placeFor = (
  tree: ViewNode,
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
const stillThere = (selection: Selection, tree: ViewNode | null, columns: string[]): boolean => {
  if (selection.kind === "part") return tree !== null && nodeAt(tree, selection.path) !== undefined;
  if (selection.kind === "column") return columns.includes(selection.field);
  return true;
};

const sameDraft = (a: Draft, b: Draft) => JSON.stringify(a) === JSON.stringify(b);

/** The view open: the one asked for while the draft has it (an undo may take
 *  it away), else the default, else the first. */
const viewOpen = (views: DraftView[], wanted: string): DraftView | undefined =>
  views.find((view) => view.key === wanted) ?? views.find((view) => view.is_default) ?? views[0];

/**
 * A project's views and its task page, edited where they are seen. It takes
 * the whole screen: what can be opened and done across the top, the outline
 * of what is open on the left, it drawn with the project's tasks in the
 * middle, and the settings of what is selected on the right.
 *
 * Every change is a draft until Save, which stores the whole set; readers see
 * the saved views and page until then. The draft is held against the set as it was
 * last saved (or opened), not against the shared cache a save writes early,
 * so a save under way still counts as unsaved until the server takes it.
 * Nothing changes while a save is under way, and leaving with changes, or
 * during a save, asks first.
 */
export const ViewEditor = ({
  projectId,
  initiativeId,
  statuses,
  set,
  initialSlug,
  onClose,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** The project's views, read by someone who may configure them. */
  set: ToolViewSetRead;
  /** A view's slug, or {@link TASK_PAGE}. */
  initialSlug?: string;
  onClose: () => void;
}) => {
  const { t, i18n } = useTranslation(["projects", "common"]);
  const wide = atLeast(useWidthClass(), "md");
  const [base, setBase] = useState(() => draftOf(set));
  const [history, dispatch] = useReducer(historyReducer<Draft>, base, startHistory<Draft>);
  const draft = history.present;
  const { views } = draft;
  // The open view is named by its key, which a refreshed set keeps whatever
  // order it comes in.
  const [active, setActive] = useState(initialSlug ?? "");
  const [selected, setSelected] = useState<Selection>(VIEW_SELECTED);
  const onPage = active === TASK_PAGE;
  const current = onPage ? undefined : viewOpen(views, active);
  // Another view opened in its place (the one asked for is gone, or an undo
  // took it away), and nothing of the last stays selected.
  if (current && current.key !== active) {
    setActive(current.key);
    setSelected(VIEW_SELECTED);
  }
  const page = useMemo(() => taskPageRoot(draft.page as StoredRegions | null), [draft.page]);
  // The tree the part edits change.
  const tree = current ? cardOf(current.definition) : onPage ? page : null;
  const columns = current ? columnsOf(current.definition) : [];
  const selection = stillThere(selected, tree, columns) ? selected : VIEW_SELECTED;
  const [width, setWidth] = useState<PreviewWidth>("desktop");
  const dirty = !sameDraft(draft, base);

  const put = usePutProjectViews(projectId);
  const saving = put.isPending;

  // Someone else's save, read while nothing is changed here, is what the
  // editor starts from. One read mid-edit is set aside: this editor's save
  // replaces the whole set.
  const adopt = (stored: ToolViewSetRead) => {
    const fresh = draftOf(stored);
    setSeen(stored);
    setBase(fresh);
    dispatch({ type: "reset", present: fresh });
  };
  const [seen, setSeen] = useState(set);
  // This editor's own save, until the set read says what it answered: the
  // read lags the answer, and shows the save's early copy before it.
  const [awaiting, setAwaiting] = useState<Draft | null>(null);
  const latest = useRef(set);
  latest.current = set;
  if (seen !== set && !saving) {
    setSeen(set);
    if (awaiting) {
      if (sameDraft(draftOf(set), awaiting)) setAwaiting(null);
    } else if (!dirty) {
      adopt(set);
    }
  }

  const { data: definitions = [] } = useProperties({ initiativeId });
  const plugins = usePluginsOnItems(initiativeId);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );

  const changeDraft = (next: Draft, then?: Selection) => {
    if (saving) return;
    dispatch({ type: "change", present: next });
    if (then) setSelected(then);
  };
  const changeViews = (next: DraftView[], then?: Selection) =>
    changeDraft({ ...draft, views: next }, then);
  const changeView = (next: (view: DraftView) => DraftView, then?: Selection) =>
    changeViews(
      views.map((view) => (view.key === current?.key ? next(view) : view)),
      then
    );
  const changeDefinition = (definition: ViewDefinitionInput, then?: Selection) =>
    changeView((view) => ({ ...view, definition }), then);
  /** The open tree, changed: a view's card, or the page, which is then the
   *  project's own. */
  const changeTree = (next: ViewNode, then?: Selection) => {
    if (current) changeDefinition(withCard(current.definition, next), then);
    else if (onPage) changeDraft({ ...draft, page: storedLayout(next) }, then);
  };

  const edits: ViewEdits = {
    select: setSelected,
    setDefinition: (definition) => changeDefinition(definition),
    rename: (name) => changeView((view) => ({ ...view, name })),
    makeDefault: () =>
      changeViews(views.map((view) => ({ ...view, is_default: view.key === current?.key }))),
    movePart: (from, to) => {
      if (!tree) return;
      changeTree(
        moveNode(tree, from, to),
        selection.kind === "part"
          ? { kind: "part", path: pathAfterMove(selection.path, from, to) }
          : selection
      );
    },
    removePart: (path) => {
      if (!tree) return;
      const after = selection.kind === "part" ? pathAfterRemove(selection.path, path) : null;
      changeTree(
        changeAt(tree, path, () => null),
        { kind: "part", path: after ?? path.slice(0, -1) }
      );
    },
    changePart: (path, node) => {
      if (!tree) return;
      changeTree(changeAt(tree, path, () => node));
    },
    addPart: (node, at) => {
      if (!tree) return;
      // A page takes what is added into its main column; a card at its end.
      const { parent, index } = at ?? placeFor(tree, selection, onPage ? [1] : []);
      // What was added is selected, to change it at once.
      changeTree(insertAt(tree, parent, node, index), {
        kind: "part",
        path: [...parent, index],
      });
    },
    resetPage: () => changeDraft({ ...draft, page: null }, VIEW_SELECTED),
    moveColumn: (from, to) => {
      if (!current) return;
      const next = [...columns];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      changeDefinition({ ...current.definition, columns: next });
    },
    removeColumn: (field) => {
      if (!current) return;
      changeDefinition(
        { ...current.definition, columns: columns.filter((each) => each !== field) },
        VIEW_SELECTED
      );
    },
    addColumn: (field, index) => {
      if (!current) return;
      const next = [...columns];
      next.splice(index ?? next.length, 0, field);
      changeDefinition({ ...current.definition, columns: next }, { kind: "column", field });
    },
  };

  // What Add offers, in the outline and at a point on the canvas, and what a
  // pick does there.
  const { labelOf, partLabel, pickerPlugins } = usePartLabel(fields, plugins);
  const translate = t as TranslateFn;
  const choices = current
    ? viewChoices(current.definition, fields, pickerPlugins, translate)
    : pageChoices(page, fields, pickerPlugins, translate);
  const addersAt = (place?: Place): Adders =>
    current?.definition.layout.type === "table"
      ? { onField: (field) => edits.addColumn(field.id, place?.index), onPart: noop, onNode: noop }
      : {
          onField: (field) => edits.addPart({ type: "field", props: { field: field.id } }, place),
          onPart: (plugin, part) =>
            edits.addPart({ type: "plugin", props: { plugin, part } }, place),
          onNode: (node) => edits.addPart(node, place),
        };
  // The regions of a page, and a card itself, stay where they are.
  const fixedDepth = onPage ? 1 : 0;
  const holds = (of: Selection) =>
    of.kind === "part" && tree !== null && HOLDERS.has(nodeAt(tree, of.path)?.type ?? "");
  const tools: CanvasTools = {
    locked: saving,
    nameOf: (of) => {
      if (of.kind === "column") {
        const field = fields.get(of.field);
        return field ? labelOf(field) : "";
      }
      const node = of.kind === "part" && tree ? nodeAt(tree, of.path) : undefined;
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
      if (of.kind !== "part" || !tree || of.path.length <= fixedDepth) return null;
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
      if (from.kind !== "part" || over.kind !== "part" || !tree) return;
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

  // A view is opened (and a new one added) as the last of the views with
  // nothing selected, so its name and layout are what the settings show.
  const newKey = useRef(0);
  const openView = (view: DraftView, next: DraftView[]) => {
    changeViews(next, VIEW_SELECTED);
    setActive(view.key);
  };
  /** A copy's name, its source's shortened to leave room for the rest. */
  const copyName = (from: DraftView) => {
    const name = viewName({ slug: from.slug ?? "", name: from.name }, t);
    const over = t("viewEditor.copyOf", { name }).length - MAX_NAME_LENGTH;
    return t("viewEditor.copyOf", {
      name: over > 0 ? `${name.slice(0, name.length - over - 1)}…` : name,
    });
  };
  const addView = (from?: DraftView) => {
    newKey.current += 1;
    const view: DraftView = {
      key: `new:${newKey.current}`,
      name: from ? copyName(from) : t("viewEditor.newView"),
      is_default: false,
      definition: from?.definition ?? { layout: { type: "board" } },
    };
    openView(view, [...views, view]);
  };
  /** The open view goes; the default passes to the first left where it held it. */
  const deleteView = () => {
    if (!current || views.length <= 1) return;
    const rest = views.filter((view) => view.key !== current.key);
    const next = current.is_default
      ? rest.map((view, index) => ({ ...view, is_default: index === 0 }))
      : rest;
    openView(next.find((view) => view.is_default) ?? next[0], next);
  };

  // Which view is open when a save answers, which may not be the one open
  // when it was sent.
  const opened = useRef(active);
  opened.current = active;
  const save = () => {
    const keys = views.map((view) => view.key);
    put.mutate(
      viewSetWrite(
        set,
        views.map(({ key: _key, ...view }) => view),
        draft.page
      ),
      {
        onSuccess: (stored) => {
          adopt(stored);
          const answer = draftOf(stored);
          // Waited for only while the read has yet to say it.
          if (!sameDraft(draftOf(latest.current), answer)) setAwaiting(answer);
          // The server keeps the order, which names a view it named meanwhile.
          const named = stored.views[keys.indexOf(opened.current)]?.slug;
          if (named) setActive(named);
          toast.success(t("viewEditor.saved"));
        },
      }
    );
  };

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
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background"
      role="dialog"
      aria-modal="true"
      aria-label={t("viewEditor.title")}
    >
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.close")}
          onClick={close}
        >
          <X className="h-4 w-4" />
        </Button>
        <Select
          value={active}
          disabled={!wide}
          onValueChange={(value) => {
            setActive(value);
            setSelected(VIEW_SELECTED);
          }}
        >
          <SelectTrigger className="w-56" aria-label={t("viewEditor.view")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {views.map((view) => (
              <SelectItem key={view.key} value={view.key}>
                {viewName({ slug: view.slug ?? "", name: view.name }, t)}
              </SelectItem>
            ))}
            <SelectSeparator />
            <SelectItem value={TASK_PAGE}>{t("viewEditor.taskPage")}</SelectItem>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.addView")}
          disabled={!wide || saving || views.length >= MAX_VIEWS}
          onClick={() => addView()}
        >
          <Plus className="h-4 w-4" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("viewEditor.viewActions")}
              disabled={!wide || saving || !current}
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem
              disabled={views.length >= MAX_VIEWS}
              onSelect={() => addView(current)}
            >
              <Copy className="h-4 w-4" />
              {t("viewEditor.duplicateView")}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              // A project always has a view to open on.
              disabled={views.length <= 1}
              onSelect={deleteView}
            >
              <Trash2 className="h-4 w-4" />
              {t("viewEditor.deleteView")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <div className="flex-1" />
        <ToggleGroup
          type="single"
          value={width}
          onValueChange={(next) => next && setWidth(next as PreviewWidth)}
          aria-label={t("viewEditor.previewWidth")}
          disabled={!wide}
        >
          {WIDTHS.map(({ width: each, icon: Icon }) => (
            <ToggleGroupItem
              key={each}
              value={each}
              aria-label={t(`viewEditor.width.${each}`)}
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
          aria-label={t("viewEditor.undo")}
          disabled={saving || history.past.length === 0}
          onClick={() => dispatch({ type: "undo" })}
        >
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("viewEditor.redo")}
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
            setSelected(VIEW_SELECTED);
          }}
        >
          {t("viewEditor.discard")}
        </Button>
        <Button type="button" size="sm" disabled={!dirty || saving} onClick={save}>
          {saving ? t("viewEditor.saving") : t("common:save")}
        </Button>
      </header>
      {/* A screen too narrow to edit on keeps the draft, and says so. */}
      {!wide ? (
        <p className="p-6 text-muted-foreground text-sm">{t("viewEditor.compact")}</p>
      ) : onPage ? (
        <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
          <aside className="min-h-0 border-r">
            <PageOutline
              page={page}
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
            <PageCanvas
              projectId={projectId}
              initiativeId={initiativeId}
              statuses={statuses}
              page={page}
              width={width}
              selection={selection}
              onSelect={setSelected}
              tools={tools}
            />
          </main>
          <aside className="min-h-0 overflow-y-auto border-l">
            <PageSettingsPanel
              page={page}
              stored={draft.page !== null}
              fields={fields}
              selection={selection}
              edits={edits}
              locked={saving}
            />
          </aside>
        </div>
      ) : current ? (
        <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)_18rem]">
          <aside className="min-h-0 border-r">
            <ViewOutline
              view={{
                ...current,
                name: viewName({ slug: current.slug ?? "", name: current.name }, t),
              }}
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
            <ViewCanvas
              projectId={projectId}
              initiativeId={initiativeId}
              statuses={statuses}
              view={current}
              width={width}
              selection={selection}
              onSelect={setSelected}
              tools={tools}
            />
          </main>
          <aside className="min-h-0 overflow-y-auto border-l">
            <ViewSettingsPanel
              view={current}
              project={{ id: projectId, initiativeId, statuses }}
              fields={fields}
              selection={selection}
              edits={edits}
              locked={saving}
            />
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
        title={t("viewEditor.unsavedTitle")}
        description={t(saving ? "viewEditor.savingBody" : "viewEditor.unsavedBody")}
        confirmLabel={t("viewEditor.leave")}
        cancelLabel={t("viewEditor.stay")}
        onConfirm={() => {
          leaving.current = true;
          setAsking(false);
          if (blocker.status === "blocked") blocker.proceed?.();
          else onClose();
        }}
        destructive
      />
    </div>
  );
};

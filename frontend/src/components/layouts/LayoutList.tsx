import { Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DetailLayoutRead,
  GetLayoutsParams,
  ListLayoutDefinitionInput,
  ListLayoutRead,
} from "@/api/generated/initiativeAPI.schemas";
import { layoutLook } from "@/components/projects/projectTasksConfig";
import { TaskTypeDeleteDialog } from "@/components/projects/TaskTypeDeleteDialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useSaveLayouts } from "@/hooks/useToolLayouts";
import { formatDateTime } from "@/lib/formatDate";

type Layout = ListLayoutRead | DetailLayoutRead;

const isList = (layout: Layout): layout is ListLayoutRead => "is_default" in layout;

/** A definition as it is written back: what it sets, and nothing left unset. */
const setOf = (definition: ListLayoutRead["definition"]) =>
  Object.fromEntries(
    Object.entries(definition).filter(([, value]) => value != null)
  ) as ListLayoutDefinitionInput;

/**
 * A target's layouts, each with when it was last changed, or a dash while it
 * is drawn as shipped, in two groups: its views, the list it opens on marked,
 * and its pages, a project's one per task type, each named for its type.
 *
 * Given its `target` by someone who may change it, each view is shown in its
 * layout menu or hidden from here, one at least staying shown, and each task
 * type deleted with its page, one at least staying.
 */
export const LayoutList = ({
  layouts,
  target,
}: {
  layouts: Layout[];
  /** Where to save a view shown or hidden; left out, the list only reads. */
  target?: GetLayoutsParams;
}) => {
  const { t } = useTranslation(["projects", "layouts", "common"]);
  const [deleting, setDeleting] = useState<number | null>(null);
  const views = layouts.filter(isList);
  const pages = layouts.filter((layout) => !isList(layout));
  const shown = views.filter((view) => !view.hidden);
  const typed = pages.filter((page) => "task_type_id" in page && page.task_type_id).length;
  // Only a project's pages are typed, so a typed page's target names it.
  const projectId = target?.tool_id ?? null;

  const row = (layout: Layout) => {
    const { icon: Icon, labelKey } = layoutLook(layout.kind);
    const typeId = "task_type_id" in layout ? layout.task_type_id : null;
    const name =
      typeId && "task_type_name" in layout
        ? t("layouts:typedTaskLayout", { name: layout.task_type_name })
        : t(labelKey as never);
    const view = isList(layout) ? layout : null;
    return (
      <li
        key={typeId ? `${layout.kind}:${typeId}` : layout.kind}
        className="flex items-center justify-between gap-3 px-3 py-2"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className={view?.hidden ? "truncate text-muted-foreground" : "truncate"}>
            {name}
          </span>
          {view?.is_default ? (
            <Star
              className="h-3 w-3 shrink-0 fill-current text-muted-foreground"
              aria-label={t("layouts:opensFirst")}
              role="img"
            />
          ) : null}
          {view?.hidden && !target ? (
            <span className="shrink-0 text-muted-foreground text-xs">{t("layouts:hidden")}</span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-3 text-muted-foreground text-xs">
          {layout.updated_at ? (
            <time dateTime={layout.updated_at}>{formatDateTime(layout.updated_at)}</time>
          ) : (
            <span role="img" aria-label={t("layouts:asShipped")}>
              —
            </span>
          )}
          {view && target ? (
            <ViewSwitch
              target={target}
              view={view}
              // The last view shown stays shown.
              last={!view.hidden && shown.length <= 1}
              label={t("layouts:showView", { name })}
            />
          ) : null}
          {typeId && projectId !== null ? (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              // A project keeps at least one task type.
              disabled={typed <= 1}
              onClick={() => setDeleting(typeId)}
              aria-label={t("layouts:deleteTaskType", {
                name: "task_type_name" in layout ? layout.task_type_name : "",
              })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          ) : null}
        </span>
      </li>
    );
  };

  const group = (heading: string, items: Layout[]) => (
    <section aria-label={heading} className="space-y-1.5">
      <h3 className="font-medium text-muted-foreground text-xs">{heading}</h3>
      <ul className="divide-y rounded-md border text-sm">{items.map(row)}</ul>
    </section>
  );

  return (
    <>
      {/* One kind of layout alone needs no heading over it. */}
      {views.length === 0 || pages.length === 0 ? (
        <ul className="divide-y rounded-md border text-sm">{layouts.map(row)}</ul>
      ) : (
        <div className="space-y-4">
          {group(t("layouts:views"), views)}
          {group(t(typed > 0 ? "layouts:taskPages" : "layouts:pages"), pages)}
        </div>
      )}
      {projectId !== null && typed > 0 ? (
        <TaskTypeDeleteDialog
          projectId={projectId}
          typeId={deleting}
          onClose={() => setDeleting(null)}
        />
      ) : null}
    </>
  );
};

/** Whether a view shows in its target's layout menu, saved as it changes. */
const ViewSwitch = ({
  target,
  view,
  last,
  label,
}: {
  target: GetLayoutsParams;
  view: ListLayoutRead;
  last: boolean;
  label: string;
}) => {
  const save = useSaveLayouts(target);
  return (
    <Switch
      checked={!view.hidden}
      disabled={save.isPending || last}
      onCheckedChange={(next) =>
        save.mutate([
          { save: { kind: view.kind, definition: { ...setOf(view.definition), hidden: !next } } },
        ])
      }
      aria-label={label}
    />
  );
};

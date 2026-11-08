import { Pencil, Star, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DetailLayoutRead,
  ListLayoutDefinitionInput,
  ListLayoutRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { host } from "@/ui/host";
import { isListLayout, type LayoutChange } from "@/ui/layouts/layoutSet";
import { type LayoutLook, listLayoutLooks } from "@/ui/layouts/looks";
import { formatDateTime } from "@/ui/lib/formatDate";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { Switch } from "@/ui/switch";

type Layout = ListLayoutRead | DetailLayoutRead;

/** Stores changes to a target's layouts. One that fails says why itself. */
type SaveLayouts = (changes: LayoutChange[]) => Promise<unknown>;

/** Asks whether to delete the task type `typeId` with its page, while it is
 *  set; `onClose` puts it away. */
type TypeDelete = (typeId: number | null, onClose: () => void) => ReactNode;

/** Each kind of page's icon and name. */
type PageLooks = Record<DetailLayoutRead["kind"], LayoutLook>;

const noop = () => {};

/** `save`, and whether a run of it from here is under way. */
const useSaving = (save: SaveLayouts) => {
  const [pending, setPending] = useState(false);
  const run = (changes: LayoutChange[]) => {
    setPending(true);
    save(changes)
      .catch(noop)
      .finally(() => setPending(false));
  };
  return { pending, run };
};

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
 * Given `save` by someone who may change them, each view is shown in its
 * layout menu or hidden from here, one at least staying shown, and a shown one
 * made the one it opens on; and, given `typeDelete`, each task type deleted
 * with its page, one at least staying. Given its `editor` as well, each
 * layout's name opens the editor on it.
 */
export const LayoutList = ({
  layouts,
  pageLooks,
  save,
  typeDelete,
  editor,
}: {
  layouts: Layout[];
  pageLooks: PageLooks;
  /** Saves a view shown or hidden; left out, the list only reads. */
  save?: SaveLayouts;
  typeDelete?: TypeDelete;
  /** The layout editor's address. */
  editor?: string;
}) => {
  const { t } = useTranslation(["projects", "layouts", "common"]);
  const [deleting, setDeleting] = useState<number | null>(null);
  const views = layouts.filter(isListLayout);
  const pages = layouts.filter((layout) => !isListLayout(layout));
  const shown = views.filter((view) => !view.hidden);
  const typed = pages.filter((page) => "task_type_id" in page && page.task_type_id).length;

  const row = (layout: Layout) => {
    const { icon: Icon, labelKey } = isListLayout(layout)
      ? listLayoutLooks[layout.kind]
      : pageLooks[layout.kind];
    const typeId = "task_type_id" in layout ? layout.task_type_id : null;
    const name =
      typeId && "task_type_name" in layout
        ? t("layouts:typedTaskLayout", { name: layout.task_type_name })
        : t(labelKey as never);
    const view = isListLayout(layout) ? layout : null;
    // What the editor's `?layout=` names it by.
    const key = typeId ? `${layout.kind}:${typeId}` : layout.kind;
    const nameClass = view?.hidden ? "truncate text-muted-foreground" : "truncate";
    return (
      <li key={key} className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          {editor ? (
            <host.Link
              to={editor}
              search={{ layout: key }}
              className={`${nameClass} hover:underline`}
              aria-label={t("layouts:editLayout", { name })}
            >
              {name}
            </host.Link>
          ) : (
            <span className={nameClass}>{name}</span>
          )}
          {view?.is_default ? (
            <Star
              className="h-3 w-3 shrink-0 fill-current text-muted-foreground"
              aria-label={t("layouts:opensFirst")}
              role="img"
            />
          ) : view && save && !view.hidden ? (
            <OpensFirstButton
              save={save}
              view={view}
              label={t("layouts:makeOpensFirst", { name })}
            />
          ) : null}
          {view?.hidden && !save ? (
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
          {view && save ? (
            <ViewSwitch
              save={save}
              view={view}
              // The last view shown stays shown.
              last={!view.hidden && shown.length <= 1}
              label={t("layouts:showView", { name })}
            />
          ) : null}
          {typeId && typeDelete ? (
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
      {typeDelete && typed > 0 ? typeDelete(deleting, () => setDeleting(null)) : null}
    </>
  );
};

/**
 * A target's layouts and the way into its editor, for someone who may change
 * them. The editor needs a tablet-sized screen, and says so itself too; on a
 * narrower one this says so in place of the way in.
 */
export const LayoutsOverview = ({
  layouts,
  pageLooks,
  save,
  typeDelete,
  editor,
}: {
  layouts: Layout[];
  pageLooks: PageLooks;
  save: SaveLayouts;
  typeDelete?: TypeDelete;
  /** The layout editor's address. */
  editor: string;
}) => {
  const { t } = useTranslation("layouts");
  const wide = atLeast(useWidthClass(), "md");
  return (
    <div className="space-y-4">
      <LayoutList
        layouts={layouts}
        pageLooks={pageLooks}
        save={save}
        typeDelete={typeDelete}
        editor={wide ? editor : undefined}
      />
      {wide ? (
        <Button asChild variant="outline" size="sm">
          <host.Link to={editor}>
            <Pencil className="h-4 w-4" />
            {t("open")}
          </host.Link>
        </Button>
      ) : (
        <p className="text-muted-foreground text-sm">{t("compact")}</p>
      )}
    </div>
  );
};

/** Whether a view shows in its target's layout menu, saved as it changes. */
const ViewSwitch = ({
  save,
  view,
  last,
  label,
}: {
  save: SaveLayouts;
  view: ListLayoutRead;
  last: boolean;
  label: string;
}) => {
  const { pending, run } = useSaving(save);
  return (
    <Switch
      checked={!view.hidden}
      disabled={pending || last}
      onCheckedChange={(next) =>
        run([
          { save: { kind: view.kind, definition: { ...setOf(view.definition), hidden: !next } } },
        ])
      }
      aria-label={label}
    />
  );
};

/** Make a shown view the one its target opens on. */
const OpensFirstButton = ({
  save,
  view,
  label,
}: {
  save: SaveLayouts;
  view: ListLayoutRead;
  label: string;
}) => {
  const { pending, run } = useSaving(save);
  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-6 w-6 shrink-0 text-muted-foreground"
      disabled={pending}
      onClick={() => run([{ opensOn: view.kind }])}
      aria-label={label}
      title={label}
    >
      <Star className="h-3 w-3" />
    </Button>
  );
};

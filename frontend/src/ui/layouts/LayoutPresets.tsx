import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import type { ListLayoutReadKind, SortField } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import type { ListLayout } from "@/ui/layouts/draft";
import type { FieldDef, LayoutEnv } from "@/ui/layouts/fields";
import {
  MAX_PRESETS,
  type Preset,
  type PresetKind,
  presetName,
  presetSlug,
  presetsOf,
  storedPreset,
} from "@/ui/layouts/presets";

import type { LayoutEdits } from "./LayoutEditor";

/** The control that picks the one field a preset sorts `list` by, naming
 *  the fields as the list does; nothing where a preset does not sort it. */
type SortControls = (
  list: ListLayoutReadKind,
  value: SortField | null,
  onChange: (next: SortField | null) => void,
  fields: ReadonlyMap<string, FieldDef>
) => ReactNode;

/** A tool's presets, as the editor changes them: the presets it reads, what
 *  one that narrows nothing holds, its list's own filter controls, and, where
 *  a preset can sort its list (a table, which a person sorts), the control
 *  that picks the sort. */
export type EditablePresets = {
  kind: PresetKind<unknown>;
  empty: unknown;
  controls: (value: unknown, onChange: (next: unknown) => void) => ReactNode;
  sortControls?: SortControls;
};

/** `presets` as the editor takes them, whatever filters they hold. */
export const editablePresets = <F,>(presets: {
  kind: PresetKind<F>;
  empty: F;
  controls: (value: F, onChange: (next: F) => void) => ReactNode;
  sortControls?: SortControls;
}): EditablePresets => presets as unknown as EditablePresets;

/**
 * The presets a list offers: each one's name, and buttons to change, move or
 * remove it, then one to add another. They are kept with the layout, and
 * saved with it.
 */
export const LayoutPresets = ({
  t,
  layout,
  of,
  fields,
  edits,
}: {
  /** Reads the words of the kind it lists, its shipped presets' names among
   *  them. */
  t: LayoutEnv["t"];
  layout: ListLayout;
  of: EditablePresets;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const presets = presetsOf(layout.definition, of.kind);
  // The preset open in the dialog, by its place; null adds one.
  const [open, setOpen] = useState<{ index: number | null } | null>(null);

  const change = (next: Preset<unknown>[]) =>
    edits.changePresets(next.map((preset) => storedPreset(preset, of.kind)));
  const move = (index: number, by: number) => {
    const next = [...presets];
    const [moved] = next.splice(index, 1);
    next.splice(index + by, 0, moved);
    change(next);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{t("layouts:presets.heading")}</h3>
        <p className="text-muted-foreground text-xs">{t("layouts:presets.help")}</p>
      </div>
      {presets.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("layouts:presets.none")}</p>
      ) : (
        <ul className="space-y-1">
          {presets.map((preset, index) => {
            const name = presetName(preset, t);
            return (
              <li key={preset.slug} className="flex items-center gap-1">
                <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={t("layouts:presets.edit", { name })}
                  onClick={() => setOpen({ index })}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={t("layouts:presets.moveUp", { name })}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={t("layouts:presets.moveDown", { name })}
                  disabled={index === presets.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={t("layouts:presets.remove", { name })}
                  onClick={() => change(presets.filter((_, each) => each !== index))}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={presets.length >= MAX_PRESETS}
        onClick={() => setOpen({ index: null })}
      >
        <Plus className="h-4 w-4" />
        {t("layouts:presets.add")}
      </Button>
      {presets.length >= MAX_PRESETS ? (
        <p className="text-muted-foreground text-xs">
          {t("layouts:presets.full", { count: MAX_PRESETS })}
        </p>
      ) : null}
      {open ? (
        <PresetDialog
          t={t}
          preset={open.index === null ? null : presets[open.index]}
          list={layout.kind}
          of={of}
          fields={fields}
          onClose={() => setOpen(null)}
          onSubmit={(name, filters, sorting) => {
            const next = [...presets];
            if (open.index === null) {
              const slug = presetSlug(
                name,
                presets.map((each) => each.slug)
              );
              next.push({ slug, name, filters, sorting });
            } else {
              // A rename keeps the slug, so links to it still open it. A shipped
              // one keeps being named in each reader's words until renamed.
              const was = next[open.index];
              const renamed = name !== presetName(was, t);
              next[open.index] = {
                ...was,
                name,
                nameKey: renamed ? undefined : was.nameKey,
                filters,
                sorting,
              };
            }
            change(next);
            setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
};

/** A preset's name, filters and, on a table, sort, changed together. */
const PresetDialog = ({
  t,
  preset,
  list,
  of,
  fields,
  onClose,
  onSubmit,
}: {
  t: LayoutEnv["t"];
  /** The preset changed, or null for a new one. */
  preset: Preset<unknown> | null;
  /** The list it is offered on. */
  list: ListLayoutReadKind;
  of: EditablePresets;
  fields: ReadonlyMap<string, FieldDef>;
  onClose: () => void;
  onSubmit: (name: string, filters: unknown, sorting: Preset<unknown>["sorting"]) => void;
}) => {
  const [name, setName] = useState(preset ? presetName(preset, t) : "");
  const [filters, setFilters] = useState(preset ? preset.filters : of.empty);
  const [sort, setSort] = useState<SortField | null>(
    of.kind.sorting?.stored(preset?.sorting ?? [])[0] ?? null
  );
  const trimmed = name.trim();

  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent className="sm:max-w-2xl">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onSubmit(trimmed, filters, sort ? (of.kind.sorting?.read([sort]) ?? []) : []);
          }}
          className="space-y-4"
        >
          <DialogHeader>
            <DialogTitle>
              {t(preset ? "layouts:presets.editTitle" : "layouts:presets.addTitle")}
            </DialogTitle>
            <DialogDescription>{t("layouts:presets.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <Field label={t("layouts:presets.name")}>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={100}
              autoFocus
            />
          </Field>
          {of.controls(filters, setFilters)}
          {of.sortControls?.(list, sort, setSort, fields)}
          <DialogFooter submitLabel={t("ui:done")} disabled={!trimmed} />
        </form>
      </DialogContent>
    </Dialog>
  );
};

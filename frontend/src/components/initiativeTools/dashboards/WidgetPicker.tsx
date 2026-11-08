/**
 * "Which widget?" — browse, preview, add.
 *
 * One flat list of widgets, searchable, with a live preview of whichever is
 * selected. The preview is not a screenshot: it is the widget itself, run in the
 * sandbox over `sampleData`, validated and drawn by the same renderer a placed
 * tile uses. So what someone sees before adding is what they get, and a widget
 * that cannot draw shows that here rather than after it lands on the canvas.
 *
 * There is deliberately no second "ready-made" list. A preset is a primitive
 * plus fixed options, and every one of those options is already a control on the
 * card — so "bar chart" is the chart widget with Bar chosen, previewed, rather
 * than a separate entry saying the same thing. Presets remain a *storage*
 * concept: an installed listing may still name one, and the backend resolves it.
 *
 * Names, descriptions, and option labels come from each widget module's own
 * `meta`, which is what lets an installed listing describe itself here without
 * an app release. The dialog's own chrome — and the binding *source* names,
 * which are our endpoints — stay plugin-owned.
 */

import type { TFunction } from "i18next";
import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  WidgetCatalog,
  WidgetCatalogEntry,
  WidgetOption,
} from "@/api/generated/initiativeAPI.schemas";
import { useWidgetMetas } from "@/hooks/useWidgetMeta";
import { MAX_WIDGETS } from "@/lib/widgets/definition";
import { sampleFor } from "@/lib/widgets/sampleData";
import { resolveMapping } from "@/lib/widgets/shape";
import { localized, type WidgetMeta, widgetDisplayName } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

import { WidgetTile } from "./WidgetTile";

export interface WidgetPickerProps {
  catalog: WidgetCatalog | undefined;
  widgetCount: number;
  onAdd: (type: string, source: string, options?: Record<string, string>) => void;
}

/** A catalog entry with everything the list needs to be searched and read. */
interface PickerItem {
  entry: WidgetCatalogEntry;
  meta: WidgetMeta | null;
  name: string;
  description: string;
  /** Name, description, and every option and source label, lowercased — so
   *  searching "pie" finds the chart that can draw one. */
  haystack: string;
}

/**
 * Where a freshly added widget points.
 *
 * Always a statement, because that is what a widget draws. The author writes it
 * in the config dialog; until they do, the widget sits unconfigured rather than
 * showing somebody else's idea of a default.
 */
const NEW_WIDGET_SOURCE = "query";

/** What a widget needs its columns to be, as a line under its name. Read off
 *  the shape it declares, so it is the same answer the picker filters on. */
const shapeSummary = (entry: WidgetCatalogEntry, t: TFunction<"dashboards">): string =>
  entry.shape
    .map((slot) => {
      const name = t(`slot.${slot.name}` as const, { defaultValue: slot.name });
      return slot.required ? name : `${name}?`;
    })
    .join(" · ");

/** The options a widget is added with: the ones that are a choice. A value
 *  of its own, such as a target, is set once the widget has data to aim. */
const choices = (entry: WidgetCatalogEntry) =>
  entry.options.filter((option) => option.kind !== "number" && option.kind !== "date");

export function WidgetPicker({ catalog, widgetCount, onAdd }: WidgetPickerProps) {
  const { t, i18n } = useTranslation("dashboards");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const language = i18n.language;

  const atCap = widgetCount >= MAX_WIDGETS;
  const entries = useMemo(() => catalog?.widgets ?? [], [catalog]);
  const types = useMemo(() => entries.map((entry) => entry.type), [entries]);
  const metas = useWidgetMetas(types);

  const items = useMemo<PickerItem[]>(
    () =>
      entries.map((entry) => {
        const meta = metas[entry.type] ?? null;
        const name = widgetDisplayName(meta, entry.type, language);
        const description = localized(meta?.description, language) ?? "";
        const optionLabels = choices(entry).flatMap((option) => [
          optionLabel(option, meta, language),
          ...option.values.map((value) => valueLabel(option.key, value, meta, language)),
        ]);
        const shapeLabel = shapeSummary(entry, t);
        return {
          entry,
          meta,
          name,
          description,
          haystack: [name, description, ...optionLabels, shapeLabel].join(" ").toLowerCase(),
        };
      }),
    [entries, metas, language, t]
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => item.haystack.includes(needle));
  }, [items, query]);

  // Whatever is chosen, as long as the search still shows it — otherwise the
  // first result, so there is always something previewed to look at.
  const selected = filtered.find((item) => item.entry.type === chosen) ?? filtered[0] ?? null;

  return (
    <div className="flex items-center gap-2">
      {atCap && (
        <span className="text-muted-foreground text-xs">
          {t("canvas.widgetCap", { max: MAX_WIDGETS })}
        </span>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size="sm" disabled={atCap || !catalog}>
            <Plus className="h-4 w-4" />
            {t("canvas.addWidget")}
          </Button>
        </DialogTrigger>
        <DialogContent className="flex h-[min(44rem,90vh)] w-[min(72rem,95vw)] max-w-none flex-col gap-4 sm:max-w-none">
          <DialogHeader>
            <DialogTitle>{t("picker.title")}</DialogTitle>
            <DialogDescription>{t("picker.description")}</DialogDescription>
          </DialogHeader>

          <div className="relative shrink-0">
            <Search
              className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("picker.searchPlaceholder")}
              aria-label={t("picker.searchPlaceholder")}
              className="pl-9"
            />
          </div>

          {selected ? (
            <div className="grid min-h-0 flex-1 gap-4 sm:grid-cols-[15rem_minmax(0,1fr)]">
              <ul
                className="max-h-40 min-h-0 space-y-1 overflow-y-auto pr-1 sm:max-h-none"
                aria-label={t("picker.listLabel")}
              >
                {filtered.map((item) => (
                  <li key={item.entry.type}>
                    <button
                      type="button"
                      onClick={() => setChosen(item.entry.type)}
                      aria-current={selected?.entry.type === item.entry.type}
                      className={cn(
                        "w-full rounded-md px-3 py-2 text-left transition-colors hover:bg-accent",
                        selected?.entry.type === item.entry.type && "bg-accent"
                      )}
                    >
                      <span className="block truncate font-medium text-sm">{item.name}</span>
                      {item.description && (
                        <span className="mt-0.5 line-clamp-2 block text-muted-foreground text-xs">
                          {item.description}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>

              <WidgetDetail
                // Remounting on the widget rather than on every keystroke: the
                // source and option choices belong to the widget being looked
                // at, and should survive narrowing the search.
                key={selected.entry.type}
                item={selected}
                onAdd={(source, options) => {
                  onAdd(selected.entry.type, source, options);
                  setOpen(false);
                }}
              />
            </div>
          ) : (
            // Said once, in the space the results would have filled — not in the
            // list *and* beside it.
            <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed p-6 text-center text-muted-foreground text-sm">
              {t("picker.noResults", { query: query.trim() })}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * The selected widget: what it draws, what it can point at, and how it looks.
 *
 * Every control here changes the preview, which is the whole point — the widget
 * re-runs against the new sample and shows the result before anything is added.
 */
function WidgetDetail({
  item,
  onAdd,
}: {
  item: PickerItem;
  onAdd: (source: string, options?: Record<string, string>) => void;
}) {
  const { t, i18n } = useTranslation("dashboards");
  const { entry, meta, name, description } = item;
  const [options, setOptions] = useState<Record<string, string>>({});
  const language = i18n.language;

  // Previewed over rows shaped the way this widget draws, so somebody choosing
  // one sees the real thing rather than a description of it.
  const data = useMemo(() => sampleFor(entry.type), [entry.type]);
  const slots = useMemo(() => resolveMapping(data.columns, entry.shape), [data, entry.shape]);

  return (
    <div className="flex min-h-0 min-w-0 flex-col gap-3">
      {/* min-w-0 + overflow-hidden: a wide preview (a table) clips inside its
          pane instead of forcing the dialog wider than the screen. */}
      <div className="h-52 shrink-0 overflow-hidden rounded-lg border bg-card p-3">
        <WidgetTile type={entry.type} data={data} config={options} slots={slots} chromeless />
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        <div className="space-y-1">
          <h3 className="font-semibold text-base">{name}</h3>
          {description && <p className="text-muted-foreground text-sm">{description}</p>}
        </div>

        {entry.shape.length > 0 && (
          <div className="space-y-1.5">
            <Label>{t("picker.data")}</Label>
            <p className="text-muted-foreground text-sm">{shapeSummary(entry, t)}</p>
          </div>
        )}

        {choices(entry).map((option) => (
          <fieldset key={option.key} className="space-y-1.5">
            <legend className="font-medium text-sm">{optionLabel(option, meta, language)}</legend>
            <div className="flex flex-wrap gap-1.5">
              {option.values.map((value) => {
                // The catalog's default is what the widget draws when the
                // picker pins nothing, so it shows as chosen from the start.
                const active = (options[option.key] ?? option.default) === value;
                return (
                  <Button
                    key={value}
                    type="button"
                    size="sm"
                    variant={active ? "default" : "outline"}
                    aria-pressed={active}
                    onClick={() =>
                      setOptions((current) => {
                        // Clicking the active choice clears it, so a widget can
                        // be added on its own default rather than pinned to a
                        // value the picker happened to show.
                        const { [option.key]: previous, ...rest } = current;
                        return previous === value ? rest : { ...rest, [option.key]: value };
                      })
                    }
                  >
                    {valueLabel(option.key, value, meta, language)}
                  </Button>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>

      <Button
        className="shrink-0 self-end"
        onClick={() => onAdd(NEW_WIDGET_SOURCE, Object.keys(options).length ? options : undefined)}
      >
        <Plus className="h-4 w-4" />
        {t("picker.add", { widget: name })}
      </Button>
    </div>
  );
}

/** An option's label in the viewer's language, falling back to its key — the
 *  widget owns these, so a module that ships no `meta` still reads sensibly. */
const optionLabel = (option: WidgetOption, meta: WidgetMeta | null, language: string): string =>
  localized(meta?.options?.[option.key]?.label, language) ?? option.key;

const valueLabel = (
  key: string,
  value: string,
  meta: WidgetMeta | null,
  language: string
): string => localized(meta?.options?.[key]?.values?.[value], language) ?? value;

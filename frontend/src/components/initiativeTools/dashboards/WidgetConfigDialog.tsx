/**
 * "What does this widget hook up to?" — with the answer visible while you decide.
 *
 * Setting up a binding is *authoring*: it writes the dashboard's own row and
 * takes DAC write, as distinct from a widget interacting with the data it shows,
 * which nothing here can do. Every control below chooses a source, an id, or a
 * comparison; none of them can name an endpoint, and the source list comes from
 * the served catalog, so this dialog can only ever offer what the backend
 * validator would accept.
 *
 * Two changes from the version that shipped first:
 *
 * **It previews.** The right pane runs the real widget over the real data, in
 * the same sandbox and renderer a placed tile uses. A binding that returns
 * nothing now shows that here, while it can still be fixed, rather than after
 * it lands on the canvas.
 *
 * **Its controls are generated from the source registry.** The per-source `if`
 * ladder this file used to be was a second copy of knowledge `sources.ts` now
 * holds, and it was why `conditions` — accepted and stored since dashboards
 * shipped — had no control at all.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  FileType,
  type QueryBuildRequest,
  type WidgetCatalog,
} from "@/api/generated/initiativeAPI.schemas";
import { type PluginEndpointRead, pluginWidgetEntry, pluginWidgetSource } from "@/api/pluginData";
import { QueryBuilder } from "@/components/initiativeTools/dashboards/QueryBuilder";
import { SqlEditor } from "@/components/initiativeTools/dashboards/SqlEditor";
import { PluginParamControl } from "@/components/plugins/PluginParamControl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWidgetCatalog } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useFilesList } from "@/hooks/useFiles";
import { usePluginWidgetCatalog } from "@/hooks/usePluginData";
import { useQueryBuilder } from "@/hooks/useQueryBuilder";
import { useQueryShape } from "@/hooks/useQueryShape";
import { useFieldCatalogs, useQueryVocabulary } from "@/hooks/useQueryVocabulary";
import { useServerForm } from "@/hooks/useServerForm";
import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { getErrorMessage } from "@/lib/errorMessage";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import { catalogEntry, type DefinitionWidget, isPluginWidgetType } from "@/lib/widgets/definition";
import { withParamAnswer } from "@/lib/widgets/pluginParams";
import { canDraw, resolveMapping } from "@/lib/widgets/shape";
import { shapeFor } from "@/lib/widgets/shapes";
import {
  type EntityKind,
  type EntityParam,
  paramsFor,
  type SourceParam,
  sourceDescriptor,
} from "@/lib/widgets/sources";
import { localized } from "@/lib/widgets/widgetMeta";

import { WidgetTile } from "./WidgetTile";

/** The only source a plug-in widget binds. A namespaced type says which plug-in and
 *  which widget; `plugin` is what it draws through, always. */
const PLUGIN_SOURCES: WidgetSource[] = ["plugin"];

export interface WidgetConfigDialogProps {
  widget: DefinitionWidget | null;
  catalog: WidgetCatalog | undefined;
  /** The dashboard's initiative. Every picker below offers this initiative's
   *  content and nothing else — a dashboard is an initiative's tool, and its
   *  bindings cannot reach outside it. */
  initiativeId: number;
  /** The dashboard row, so the preview resolves exactly as the placed tile
   *  will. Absent for a widget that is not on a dashboard yet. */
  dashboardId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (patch: Partial<DefinitionWidget>) => void;
}

export function WidgetConfigDialog({
  widget,
  catalog,
  initiativeId,
  dashboardId,
  open,
  onOpenChange,
  onSave,
}: WidgetConfigDialogProps) {
  const { t, i18n } = useTranslation(["dashboards", "common"]);
  const { meta } = useWidgetMeta(widget?.type ?? "");

  // Filled in from the widget each time the dialog opens, so a cancelled edit
  // leaves nothing behind — and a refetch part-way through one does not either.
  const form = useServerForm(
    widget,
    (loaded) => ({
      title: loaded?.title ?? "",
      binding: loaded?.binding ?? ({ source: "query" } as WidgetBinding),
      options: loaded?.options ?? ({} as Record<string, string>),
    }),
    [open, widget?.id],
    (a, b) => JSON.stringify(a) === JSON.stringify(b)
  );
  const { title, binding, options } = form.values;
  const setTitle = (next: string) => form.set({ title: next });
  // Both take an updater as well as a value, the way the state they replaced
  // did — several handlers here change one key of the object they read.
  const setBinding = (next: WidgetBinding | ((current: WidgetBinding) => WidgetBinding)) =>
    form.set((previous) => ({
      binding: typeof next === "function" ? next(previous.binding) : next,
    }));
  const setOptions = (
    next: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)
  ) =>
    form.set((previous) => ({
      options: typeof next === "function" ? next(previous.options) : next,
    }));

  /**
   * An installed plug-in's widget is not in the built-in catalog, and looking for
   * it there is what left this dialog with nothing to offer.
   *
   * The two catalogs answer different questions and are served separately: the
   * built-in one is this build's own vocabulary — size floors, bindable
   * sources, display options per primitive — while a plug-in's widgets come from
   * each install's pinned definition. A namespaced `plugin:<uid>:<widget>` type
   * has never been in the first, so `catalogEntry` missed, `sources` fell back
   * to `[]`, and the source list rendered empty for every plug-in widget on the
   * canvas.
   *
   * A plug-in widget binds one source and it is always `plugin` — that is what the
   * namespaced type means — so the list does not need looking up at all.
   */
  const isPlugin = isPluginWidgetType(widget?.type ?? "");
  //: A plug-in's *data*, whoever draws it — its own widget, or one of ours
  //: pointed at it with a statement.
  const readsPlugin = isPlugin || binding.source === "plugin";
  const pluginCatalog = usePluginWidgetCatalog(open && readsPlugin);
  // A plug-in widget resolves its plug-in from its own namespaced type. One of ours
  // has no such type, so it resolves the plug-in it *named* — which is the only
  // difference between the two, and why the picker below exists at all.
  const plugin = useMemo(() => {
    const byType = pluginWidgetEntry(pluginCatalog.data, widget?.type ?? "");
    if (byType) return byType;
    const named = (pluginCatalog.data?.items ?? []).find(
      (item) => item.plugin_uid === binding.plugin_uid
    );
    return named ? { entry: named, widget: undefined } : undefined;
  }, [pluginCatalog.data, widget?.type, binding.plugin_uid]);

  const entry = catalogEntry(catalog, widget?.type ?? "");
  // A built-in widget reads a plug-in too, as far as the rows are described: a
  // statement names what it returns, over columns the endpoint declared it
  // hands back. Without one they are the plug-in's own shape, which only the plug-in's
  // own module knows how to draw — so the source is offered and the statement
  // is what makes it usable.
  const sources: string[] = isPlugin ? PLUGIN_SOURCES : ["query", "sheet_range", "plugin"];
  const source = binding.source;
  const descriptor = sourceDescriptor(source);

  /**
   * Which of the plug-in's reads this widget may be pointed at.
   *
   * A widget names the endpoints it draws, and those are the ones offered. One
   * that names none is offered every read the plug-in has — a publisher who did not
   * narrow it has not said it should be narrowed here.
   */
  const pluginEndpoints = useMemo((): PluginEndpointRead[] => {
    const all = plugin?.entry.endpoints ?? [];
    const named = plugin?.widget?.endpoints ?? [];
    if (!named.length) return all;
    return all.filter((candidate) => named.includes(candidate.id));
  }, [plugin]);

  const pluginEndpoint = pluginEndpoints.find((candidate) => candidate.id === binding.endpoint_id);
  const pluginParams = (binding.params ?? {}) as Record<string, unknown>;

  // Which lists this source's controls need. Enabled only while the control is
  // on screen, so opening the dialog for a statement fetches nothing.
  const params = paramsFor(source);
  const needs = (kind: EntityKind) =>
    open && params.some((p) => p.kind === "entity" && p.entity === kind);

  const files = useFilesList(
    { file_type: FileType.sheet, initiative_id: initiativeId },
    { enabled: needs("file") }
  );

  const entityOptions = useMemo(
    (): Record<EntityKind, { value: string; label: string }[]> => ({
      file: (files.data?.items ?? []).map((file) => ({
        value: String(file.id),
        label: file.name,
      })),
    }),
    [files.data]
  );

  // A binding for a plug-in widget names its install. Filled in from the type
  // rather than typed: `plugin:<uid>:<widget>` already carries the uid, and a
  // definition whose binding disagrees with its type is one the server refuses.
  const setForm = form.set;
  useEffect(() => {
    if (!open || !plugin) return;
    setForm(({ binding }) => ({
      binding:
        binding.source === "plugin" && binding.plugin_uid === plugin.entry.plugin_uid
          ? binding
          : { ...binding, source: "plugin", plugin_uid: plugin.entry.plugin_uid },
    }));
  }, [open, plugin, setForm]);

  const setBindingValue = (patch: Partial<WidgetBinding>) =>
    setBinding((current) => ({ ...current, ...patch }));

  /**
   * One of the plug-in endpoint's own parameters.
   *
   * An emptied field is *removed* rather than sent as `""`, because a parameter
   * absent and a parameter answered with nothing are different things to the
   * plug-in — and an empty list is the same "nothing" as an empty string.
   *
   * Changing one clears whatever was chosen *from* it. A menu filled through
   * `needs` was filled for the sibling's old value — an aisle belongs to the
   * shop that was chosen when it was picked — so leaving it behind is how a
   * binding ends up naming an aisle of a shop it no longer reads. Cleared to a
   * fixpoint, because a dependent can itself have dependents.
   */
  const setPluginParam = (key: string, value: unknown) =>
    setBinding((current) => {
      const next = withParamAnswer(
        pluginEndpoint?.params ?? [],
        (current.params ?? {}) as Record<string, unknown>,
        key,
        value
      );
      return { ...current, params: Object.keys(next).length ? next : undefined };
    });

  /** Pointing a widget at a different read drops the old one's answers: they
   *  were that endpoint's parameters, and they are not this one's. */
  const setPluginEndpoint = (endpointId: string) =>
    setBinding((current) => ({ ...current, endpoint_id: endpointId, params: undefined }));

  /**
   * A plug-in binding without a read is one the server refuses.
   *
   * `endpoint_id` is required where a dashboard definition is normalized, so
   * saving a freshly added plug-in widget that has not been pointed at anything
   * comes back a 422 — after the dialog has already closed, which is the worst
   * place to find out. The control that fills it is right there, so the answer
   * is to not offer the save rather than to explain the failure afterwards.
   */
  // A plug-in binding without a read is one the server refuses, whichever kind of
  // widget carries it — and one of ours has a plug-in to name as well.
  const incomplete = readsPlugin && (!binding.endpoint_id || !binding.plugin_uid);

  /**
   * The same, for a statement the server would refuse.
   *
   * A statement is checked where a definition is normalized, so saving a
   * refused one takes the whole dashboard with it: the update comes back a 422
   * and nothing on the canvas saves until the widget is opened again and
   * fixed. The reason is already beside the box that produced it, so again —
   * do not offer the save rather than explain the failure afterwards.
   *
   * `checking` is not a refusal, but it is not an answer either, and what it
   * covers is the few hundred milliseconds after the last keystroke.
   */
  const [queryStatus, setQueryStatus] = useState<QueryStatus>("ok");
  const unsaveable = incomplete || queryStatus !== "ok";

  const save = () => {
    if (unsaveable) return;
    onSave({
      title: title.trim() || undefined,
      binding,
      options: Object.keys(options).length ? options : undefined,
    });
    onOpenChange(false);
  };

  if (!widget) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("dashboards:config.title")}</DialogTitle>
          <DialogDescription>
            {localized(meta?.description, i18n.language) ?? t("dashboards:config.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="grid max-h-[60vh] gap-6 overflow-y-auto md:grid-cols-[1fr_18rem]">
          <div className="space-y-5">
            <section className="space-y-2">
              <Label htmlFor="widget-title">{t("dashboards:config.widgetTitle")}</Label>
              <Input
                id="widget-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t("dashboards:config.widgetTitlePlaceholder")}
              />
            </section>

            <section className="space-y-2">
              <h3 className="font-medium text-sm">{t("dashboards:config.sectionBinding")}</h3>
              <Label htmlFor="widget-source">{t("dashboards:config.source")}</Label>
              <Select
                value={source}
                onValueChange={(next) =>
                  // Changing the source drops the old source's ids rather than
                  // carrying a counter id onto a file binding.
                  setBinding({ source: next as WidgetBinding["source"] })
                }
              >
                <SelectTrigger id="widget-source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sources.map((option) => (
                    <SelectItem key={option} value={option}>
                      {t(`dashboards:bindingSource.${option}` as const, {
                        defaultValue: option,
                      })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {descriptor && (
                <p className="text-muted-foreground text-xs">
                  {t("dashboards:config.rowNoun", {
                    noun: t(`dashboards:provenance.rows_${descriptor.rowNoun}` as const, {
                      count: 1,
                    }).replace(/^1\s*/, ""),
                  })}
                </p>
              )}
            </section>

            {/* A plug-in widget's own controls replace these. The registry's two
                slots for it are `plugin_uid` and `endpoint_id`, and neither is a
                thing to type: one comes from the widget's type, the other is a
                choice among the reads the plug-in declares. */}
            {(readsPlugin ? [] : params).map((param) => (
              <ParamControl
                key={param.key as string}
                param={param}
                binding={binding}
                entityOptions={entityOptions}
                initiativeId={initiativeId}
                onChange={setBindingValue}
                onQueryStatus={setQueryStatus}
              />
            ))}

            {readsPlugin && (
              <section className="space-y-4">
                {!isPlugin && (
                  <div className="space-y-2">
                    <Label htmlFor="plugin-uid">{t("dashboards:config.plugin")}</Label>
                    <Select
                      value={binding.plugin_uid ?? ""}
                      onValueChange={(next) =>
                        setBindingValue({
                          plugin_uid: next,
                          // A different plug-in's reads are not this one's.
                          endpoint_id: undefined,
                          params: undefined,
                        })
                      }
                    >
                      <SelectTrigger id="plugin-uid">
                        <SelectValue placeholder={t("dashboards:config.pluginPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        {(pluginCatalog.data?.items ?? []).map((item) => (
                          <SelectItem key={item.plugin_uid} value={item.plugin_uid}>
                            {item.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="plugin-endpoint">{t("dashboards:config.pluginEndpoint")}</Label>
                  <Select value={binding.endpoint_id ?? ""} onValueChange={setPluginEndpoint}>
                    <SelectTrigger id="plugin-endpoint">
                      <SelectValue placeholder={t("dashboards:config.pluginEndpointPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {pluginEndpoints.map((candidate) => (
                        <SelectItem key={candidate.id} value={candidate.id}>
                          {candidate.id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {!pluginCatalog.isLoading && !plugin && (
                    <p className="text-muted-foreground text-xs">
                      {t("dashboards:config.pluginNotInstalled")}
                    </p>
                  )}
                </div>

                {/* The endpoint's own parameters. Which values each permits is
                    the plug-in's to answer — a repository, a label, a board are all
                    facts about one install — so a control that offers a menu
                    gets it from the plug-in rather than from anything written down
                    here. */}
                {(pluginEndpoint?.params ?? []).map((param) => (
                  <PluginParamControl
                    key={param.key}
                    param={param}
                    pluginId={plugin?.entry.plugin_id}
                    endpointId={pluginEndpoint?.id}
                    values={pluginParams}
                    open={open}
                    onChange={setPluginParam}
                  />
                ))}
              </section>
            )}

            {(entry?.options ?? []).length > 0 && (
              <section className="space-y-3">
                <h3 className="font-medium text-sm">{t("dashboards:config.sectionDisplay")}</h3>
                {/* Labelled by the widget itself, so an installed listing names
                    its own options without a locale edit here. */}
                {(entry?.options ?? []).map((option) => (
                  <div key={option.key} className="space-y-2">
                    <Label htmlFor={`widget-option-${option.key}`}>
                      {localized(meta?.options?.[option.key]?.label, i18n.language) ?? option.key}
                    </Label>
                    {option.kind === "number" || option.kind === "date" ? (
                      // A value of its own, such as a target or its day. Empty
                      // means the widget draws without one.
                      <Input
                        id={`widget-option-${option.key}`}
                        type={option.kind}
                        value={options[option.key] ?? ""}
                        onChange={(event) => {
                          const next = event.target.value;
                          setOptions((current) => {
                            const { [option.key]: _previous, ...rest } = current;
                            return next ? { ...rest, [option.key]: next } : rest;
                          });
                        }}
                      />
                    ) : (
                      <Select
                        value={options[option.key] ?? option.default}
                        onValueChange={(next) =>
                          setOptions((current) => ({ ...current, [option.key]: next }))
                        }
                      >
                        <SelectTrigger id={`widget-option-${option.key}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {option.values.map((value) => (
                            <SelectItem key={value} value={value}>
                              {localized(
                                meta?.options?.[option.key]?.values?.[value],
                                i18n.language
                              ) ?? value}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                ))}
              </section>
            )}
          </div>

          <BindingPreview
            widget={widget}
            binding={binding}
            options={options}
            initiativeId={initiativeId}
            dashboardId={dashboardId}
            moduleSource={
              isPlugin ? pluginWidgetSource(pluginCatalog.data, widget.type) : undefined
            }
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={save} disabled={unsaveable}>
            {t("common:save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** One binding parameter, drawn from what the registry says it is. */
function ParamControl({
  param,
  binding,
  entityOptions,
  initiativeId,
  onChange,
  onQueryStatus,
}: {
  param: SourceParam;
  binding: WidgetBinding;
  entityOptions: Record<EntityKind, { value: string; label: string }[]>;
  initiativeId: number;
  onChange: (patch: Partial<WidgetBinding>) => void;
  onQueryStatus: (status: QueryStatus) => void;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const key = param.key as string;

  switch (param.kind) {
    case "entity": {
      const entity = param as EntityParam;
      const value = binding[param.key];
      return (
        <section className="space-y-2">
          <Label>{t(`dashboards:bindingParam.${entity.entity}` as const)}</Label>
          <Select
            value={typeof value === "number" ? String(value) : entity.required ? "" : "all"}
            onValueChange={(next) =>
              onChange({
                [param.key]: next === "all" ? null : Number(next),
              } as Partial<WidgetBinding>)
            }
          >
            <SelectTrigger>
              <SelectValue placeholder={t("dashboards:config.choose")} />
            </SelectTrigger>
            <SelectContent>
              {!entity.required && (
                <SelectItem value="all">
                  {t(`dashboards:config.all_${entity.entity}` as const)}
                </SelectItem>
              )}
              {entityOptions[entity.entity].map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </section>
      );
    }

    case "sql":
      return (
        <QueryParam
          binding={binding}
          initiativeId={initiativeId}
          onChange={onChange}
          onStatus={onQueryStatus}
          paramKey={param.key as keyof WidgetBinding}
        />
      );

    default:
      return (
        <section className="space-y-2">
          <Label htmlFor={`param-${key}`}>
            {t(`dashboards:bindingParam.${key}` as const, { defaultValue: key })}
          </Label>
          <Input
            id={`param-${key}`}
            value={(binding[param.key] as string) ?? ""}
            placeholder={param.kind === "text" ? param.placeholder : undefined}
            onChange={(event) =>
              onChange({ [param.key]: event.target.value } as Partial<WidgetBinding>)
            }
          />
        </section>
      );
  }
}

/**
 * The widget, running against what the controls currently say.
 *
 * The viewer's own data through the viewer's own session — the preview is not a
 * privileged read, and someone configuring a widget sees exactly what they
 * would see with it placed. It resolves nothing until the widget is on a
 * dashboard, because `plugin` bindings are decided against that row.
 */
function BindingPreview({
  widget,
  binding,
  options,
  initiativeId,
  dashboardId,
  moduleSource,
}: {
  widget: DefinitionWidget;
  binding: WidgetBinding;
  options: Record<string, string>;
  initiativeId: number;
  dashboardId?: number;
  moduleSource?: string;
}) {
  const { t } = useTranslation("dashboards");
  const live = useWidgetData(binding, initiativeId, dashboardId);

  // Which columns fill the widget's slots. Resolved here for the same reason
  // the canvas resolves it there — a widget is handed ordinals, never column
  // names, and works out neither its own declared shape nor the author's
  // corrections. Without this every slot reads as unfilled and a widget that
  // draws numbers says it was given none, which is the opposite of what this
  // pane promises.
  const catalogQuery = useWidgetCatalog();
  const shape = shapeFor(widget.type, catalogQuery.data);
  const data = live.data;
  const rows = data.source === "rows";
  const slots = rows ? resolveMapping(data.columns, shape, widget.mapping) : undefined;
  // A statement that does not return the shape this widget draws falls back to
  // the table, exactly as the placed tile does — the pane says it draws what
  // the tile will draw, so the two cannot differ on this either.
  const drawable = !rows || canDraw(data.columns, shape, widget.mapping);

  return (
    <aside className="space-y-2">
      <h3 className="font-medium text-sm">{t("config.preview")}</h3>
      <div className="h-56 overflow-hidden rounded-lg border bg-card p-2">
        <WidgetTile
          type={widget.type}
          data={data}
          config={options}
          slots={slots}
          source={moduleSource}
          view={drawable ? "scene" : "table"}
          isLoading={live.isLoading}
          errorCode={live.errorCode}
          chromeless
        />
      </div>
      <p className="text-muted-foreground text-xs">{t("config.previewHint")}</p>
    </aside>
  );
}

/**
 * How a widget is pointed at data: by clicking, or by writing it.
 *
 * Two tabs over one statement, and which of them is *authoritative* is the
 * whole design. **Build** is the surface: somebody who does not write SQL has
 * to be able to build a dashboard, so what they choose is a description and the
 * server writes the statement from it — which is also what guarantees the
 * statement is one the surface will run. **SQL** is the escape: what the
 * builder cannot describe, somebody can still write.
 *
 * The moment a statement is edited by hand the description behind it stops
 * being true of it, so it is dropped and the text is what is stored. That is
 * one-way by nature — a statement carries no record of the clicking it did not
 * come from — so it happens on the first edit rather than on opening the tab,
 * and going back to the builder says what it will cost.
 *
 * Not every statement has a description behind it to begin with. The ones a
 * listing ships and the ones the cutover wrote were never clicked, so they open
 * on SQL: reading a widget's configuration must never rewrite it.
 *
 * Nothing here decides whether a statement is allowed. The server reads it the
 * way it will read it for real (`/query/describe`) and answers with the columns
 * or with the word that has to change; what is shown below the box is that
 * answer.
 */

/** Where a widget starts when nothing has been chosen yet: how many rows there
 *  are. It is the smallest query that draws something, so a new widget is
 *  never empty while its author decides what they wanted. */
const NEW_QUERY: QueryBuildRequest = {
  dataset: "tasks",
  columns: [{ field: "*", aggregate: "count", alias: "count" }],
  where: [],
  group_by: [],
};

/** Whether a widget's statement is one the server would accept. A binding with
 *  no statement at all is `ok`: that is the state a widget is in before anybody
 *  points it anywhere, and it stores fine. */
type QueryStatus = "ok" | "checking" | "refused";

function QueryParam({
  binding,
  initiativeId,
  paramKey,
  onChange,
  onStatus,
}: {
  binding: WidgetBinding;
  initiativeId: number;
  paramKey: keyof WidgetBinding;
  onChange: (patch: Partial<WidgetBinding>) => void;
  onStatus: (status: QueryStatus) => void;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const stored = (binding[paramKey] as string | undefined) ?? "";
  // `undefined` means the builder is not driving this binding: either somebody
  // has written the statement themselves, or it arrived without a description.
  const [spec, setSpec] = useState<QueryBuildRequest | undefined>(() => {
    const described = binding.spec as QueryBuildRequest | undefined;
    if (described) return { ...described, initiative_id: initiativeId };
    return stored ? undefined : { ...NEW_QUERY, initiative_id: initiativeId };
  });
  const [tab, setTab] = useState<"build" | "sql">(spec ? "build" : "sql");
  const built = useQueryBuilder(spec ?? null);

  // The statement and the description are stored together: the description is
  // what reopens the builder on what somebody built, rather than leaving them
  // to read back their own SQL.
  useEffect(() => {
    if (!spec) return;
    if (built.data?.sql && built.data.sql !== binding[paramKey]) {
      onChange({ [paramKey]: built.data.sql, spec } as Partial<WidgetBinding>);
    }
  }, [built.data?.sql, binding, paramKey, onChange, spec]);

  // What the SQL tab shows: the builder's statement while it is driving, and
  // the stored one once it is not.
  const statement = (spec ? built.data?.sql : undefined) ?? stored;

  // A statement the server wrote is one it will run, so only a hand-written
  // one is checked — and on a pause, because a half-typed name is not a
  // question worth asking. The answer describes what is in the box only once
  // the pause has caught up and the query has stopped holding the previous
  // statement's columns.
  const settled = useDebouncedValue(statement, 400);
  const shape = useQueryShape(spec ? null : statement, initiativeId);
  const checking =
    !spec &&
    Boolean(statement.trim()) &&
    (settled !== statement || shape.isFetching || shape.isPlaceholderData);

  const status: QueryStatus = spec
    ? built.isError
      ? "refused"
      : built.isFetching
        ? "checking"
        : "ok"
    : !statement.trim()
      ? "ok"
      : checking
        ? "checking"
        : shape.isError
          ? "refused"
          : "ok";

  useEffect(() => {
    onStatus(status);
  }, [status, onStatus]);

  /** An edit by hand. The description stops being true of the statement the
   *  moment it is one somebody typed, so it goes. */
  const write = (next: string) => {
    setSpec(undefined);
    onChange({ [paramKey]: next, spec: undefined } as Partial<WidgetBinding>);
  };

  return (
    <Tabs value={tab} onValueChange={(next) => setTab(next as "build" | "sql")}>
      <TabsList>
        <TabsTrigger value="build">{t("dashboards:builder.tabBuild")}</TabsTrigger>
        <TabsTrigger value="sql">{t("dashboards:builder.tabSql")}</TabsTrigger>
      </TabsList>

      <TabsContent value="build" className="space-y-3">
        {spec ? (
          <QueryBuilder spec={spec} onChange={setSpec} initiativeId={initiativeId} />
        ) : (
          <div className="space-y-2 rounded-lg border border-dashed p-3">
            <p className="text-muted-foreground text-xs">{t("dashboards:builder.notBuilt")}</p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSpec({ ...NEW_QUERY, initiative_id: initiativeId })}
            >
              {t("dashboards:builder.buildNew")}
            </Button>
          </div>
        )}
        {built.isError && (
          <p className="text-destructive text-xs">{t("dashboards:builder.refused")}</p>
        )}
      </TabsContent>

      <TabsContent value="sql" className="space-y-1.5">
        <StatementEditor
          statement={statement}
          onWrite={write}
          checking={checking}
          columns={checking || shape.isError ? undefined : shape.data?.columns}
          error={checking ? undefined : shape.error}
        />
      </TabsContent>
    </Tabs>
  );
}

/**
 * The statement, and what the server says it would return.
 *
 * What it shows about the answer is decided above, because the same answer
 * decides whether the dialog may be saved — so this is handed a settled result
 * rather than one that may still be describing the statement before this one.
 */
function StatementEditor({
  statement,
  onWrite,
  checking,
  columns,
  error,
}: {
  statement: string;
  onWrite: (next: string) => void;
  checking: boolean;
  columns?: { name: string }[];
  error?: unknown;
}) {
  const { t } = useTranslation(["dashboards", "common"]);
  const { datasets, functions, tokens } = useQueryVocabulary();
  const fields = useFieldCatalogs(datasets);

  return (
    <>
      <SqlEditor
        id="widget-sql"
        value={statement}
        onChange={onWrite}
        datasets={datasets}
        functions={functions}
        fields={fields}
        tokens={tokens}
        aria-describedby="widget-sql-answer"
      />
      <p id="widget-sql-answer" className="text-xs">
        {checking ? (
          <span className="text-muted-foreground">{t("dashboards:builder.checking")}</span>
        ) : error ? (
          <span className="text-destructive">
            {getErrorMessage(error, "dashboards:builder.refused")}
          </span>
        ) : columns ? (
          <span className="text-muted-foreground">
            {t("dashboards:builder.returns", {
              columns: columns.map((column) => column.name).join(", "),
            })}
          </span>
        ) : (
          <span className="text-muted-foreground">{t("dashboards:config.sqlHelp")}</span>
        )}
      </p>
    </>
  );
}

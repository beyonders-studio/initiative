import { useParams } from "@tanstack/react-router";
import { MoreHorizontal, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { itemSaves } from "@/hooks/useFieldSave";
import {
  pluginToolRowSaves,
  useInstalledTools,
  usePluginToolRow,
  useRunPluginToolAction,
} from "@/hooks/usePluginToolRows";
import { useRouteId } from "@/hooks/useRouteId";
import { useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  fieldChange,
  fieldStart,
  fieldValue,
  type ToolActionDecl,
  type ToolRow,
  type ToolTable,
  toolLayoutTarget,
  toolOfKind,
  toolPluginListRoute,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { Label } from "@/ui/label";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import type { StoredRegions } from "@/ui/layouts/detailLayout";
import { detailLayoutOf } from "@/ui/layouts/layoutSet";
import { Section } from "@/ui/layouts/section";
import { DetailPageSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { ToolTableRows } from "./ToolPluginView";
import { ToolFieldInput, toolDetail } from "./toolDetail";

/** What can be run on a row: its table's actions, each asked first where it
 *  says to, with a field for each of its `params`. One runs at a time. */
const RowActions = ({
  table,
  row,
  language,
}: {
  table: ToolTable;
  row: ToolRow;
  language: string;
}) => {
  const { t } = useTranslation("plugins");
  const run = useRunPluginToolAction(table.kind, table.items);
  const [asking, setAsking] = useState<ToolActionDecl | null>(null);
  // The answers to its params, as the row would hold them.
  const [answers, setAnswers] = useState<ToolRow>(row);
  if (table.actions.length === 0 || !row.can.edit) return null;
  const params = (asking?.params ?? []).flatMap((key) =>
    table.fields.filter((field) => field.key === key)
  );
  const go = (action: ToolActionDecl, onSuccess?: () => void) => {
    if (run.isPending) return;
    const given = (action.params ?? []).flatMap((key) =>
      table.fields
        .filter((field) => field.key === key)
        .map((field) => fieldChange(field, fieldValue(answers, field)))
    );
    run.mutate(
      {
        rowId: row.id,
        actionId: action.id,
        ...(given.length > 0
          ? {
              fields: Object.assign({}, ...given.map((change) => change.fields)),
              people: Object.assign({}, ...given.map((change) => change.people)),
            }
          : {}),
      },
      { onSuccess }
    );
  };
  const start = (action: ToolActionDecl) => {
    if (action.confirm || action.params?.length) {
      // Each param starts as a new row's field would.
      const starts = table.fields
        .filter((field) => action.params?.includes(field.key))
        .map((field) => fieldChange(field, fieldStart(table.fields, field)));
      setAnswers({
        ...row,
        fields: Object.assign({ ...row.fields }, ...starts.map((change) => change.fields)),
        people: Object.assign({ ...row.people }, ...starts.map((change) => change.people)),
      });
      setAsking(action);
    } else {
      go(action);
    }
  };
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="icon-sm" aria-label={t("tool.actions")}>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {table.actions.map((action) => (
            <DropdownMenuItem
              key={action.id}
              disabled={run.isPending}
              onSelect={() => start(action)}
            >
              {toolText(action.name, language)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <ConfirmDialog
        open={asking !== null}
        onOpenChange={(open) => {
          if (!open) setAsking(null);
        }}
        title={asking ? toolText(asking.name, language) : ""}
        description={asking?.confirm ? toolText(asking.confirm, language) : undefined}
        confirmLabel={asking ? toolText(asking.name, language) : ""}
        isLoading={run.isPending}
        onConfirm={(event) => {
          // It closes once the action has run.
          event.preventDefault();
          if (asking) go(asking, () => setAsking(null));
        }}
      >
        {params.length > 0 ? (
          <div className="space-y-4">
            {params.map((field) => {
              const label = toolText(field.name, language);
              return (
                <div key={field.key} className="space-y-1.5">
                  <Label>{label}</Label>
                  <ToolFieldInput
                    field={field}
                    row={answers}
                    label={label}
                    value={fieldValue(answers, field)}
                    onChange={(value) => {
                      const change = fieldChange(field, value);
                      setAnswers((held) => ({
                        ...held,
                        fields: { ...held.fields, ...change.fields },
                        people: { ...held.people, ...change.people },
                      }));
                    }}
                    initiativeId={row.initiative_id}
                    canOpen={{ tool: table.kind, id: row.id }}
                  />
                </div>
              );
            })}
          </div>
        ) : null}
      </ConfirmDialog>
    </>
  );
};

/**
 * One row of a tool plug-in, the tool's own or an item's, on its own page: its
 * table's detail layout, then the rows of each item table under it, each as
 * that table's list layout draws them.
 */
export function ToolPluginRowPage() {
  const { t, i18n } = useTranslation("plugins");
  const gp = useCommunityPath();
  const { kind = "" } = useParams({ strict: false }) as { kind?: string };
  const rowId = useRouteId("rowId");
  const initiativeId = useRouteId("initiativeId");
  const installs = useInstalledTools();
  const found = installs.status === "ready" ? toolOfKind(installs.tools, kind) : null;
  const query = usePluginToolRow(kind, found ? rowId : null);
  const row = useMemo(() => (query.data ? toolRow(query.data) : null), [query.data]);
  const table = found?.table;
  const detail = useMemo(
    () => (table ? toolDetail(table, i18n.language) : null),
    [table, i18n.language]
  );
  const saves = useMemo(() => itemSaves(pluginToolRowSaves(kind), rowId ?? 0), [kind, rowId]);
  // Its page as the place it is listed in laid it out, or as shipped.
  const layouts = useToolLayouts(
    table && row ? toolLayoutTarget(table, row.initiative_id, row.parent_id) : null
  );

  if (installs.status === "loading" || query.isLoading) {
    return (
      <SkeletonRegion>
        <DetailPageSkeleton />
      </SkeletonRegion>
    );
  }
  if (installs.status === "error") {
    return <StatusMessage title={t("tool.installsLoadError")} onRetry={installs.retry} />;
  }
  if (!found || !table || !detail || !row || initiativeId === null) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("tool.notFound")}
        description={t("tool.notFoundBody")}
        backTo={initiativeId === null ? gp("/") : gp(`/i/${initiativeId}`)}
        backLabel={t("tool.backToTool", {
          name: found ? toolText(found.tool.name, i18n.language) : "",
        })}
      />
    );
  }

  const { tool } = found;
  // The row it is an item of, which its crumb leads back to.
  const parent =
    row.parent_id !== null && table.parent
      ? {
          label: toolText(tool.tables.get(table.parent)?.name ?? {}, i18n.language),
          to: toolPluginRowRoute(row.initiative_id, table.parent, row.parent_id),
        }
      : null;
  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={{
          label: toolText(tool.name, i18n.language),
          to: toolPluginListRoute(row.initiative_id, tool.kind),
        }}
        initiativeId={row.initiative_id}
        trail={parent ? [parent] : []}
      />
      <DetailLayoutView
        detail={detail}
        item={row}
        layout={detailLayoutOf(layouts.data, table.kind) as StoredRegions | null}
        context={{
          readOnly: !row.can.edit,
          initiativeId: row.initiative_id,
          saves,
          actions: <RowActions table={table} row={row} language={i18n.language} />,
        }}
      />
      {table.items.map((itemKind) => {
        const items = tool.tables.get(itemKind);
        return items ? (
          <Section key={itemKind} title={toolText(items.name, i18n.language)}>
            <ToolTableRows
              table={items}
              initiativeId={row.initiative_id}
              parentId={row.id}
              canCreate={row.can.contribute}
            />
          </Section>
        ) : null;
      })}
    </div>
  );
}

/**
 * What can be done with one row of a tool plug-in, the tool's own or an
 * item's: its table's declared actions, then what every tool's items have,
 * each offered as the row's `can` allows it. Its access settings are the
 * tool's own row's, since an item is shared as its tool is; archiving puts it
 * away and takes it back out; deleting puts it in the trash with what is
 * under it.
 */

import { useNavigate } from "@tanstack/react-router";
import { Archive, ArchiveRestore, MoreHorizontal, Shield, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SharingSettings } from "@/components/access/SharingSettings";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import {
  useDeletePluginToolRow,
  useRunPluginToolAction,
  useSetPluginToolRowGrants,
} from "@/hooks/usePluginToolRows";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import {
  fieldChange,
  fieldChanges,
  fieldStart,
  fieldValue,
  type ToolActionDecl,
  type ToolRow,
  type ToolTable,
  toolPluginListRoute,
  toolPluginRowRoute,
  toolText,
  withChange,
} from "@/lib/toolPlugins";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { Label } from "@/ui/label";

import { ToolFieldInput } from "./toolDetail";

/** Who a tool's row is shared with, changed as a built-in tool's Access
 *  settings change it. */
const AccessDialog = ({ open, onOpenChange, row }: DialogProps & { row: ToolRow }) => {
  const { t } = useTranslation(["plugins", "access"]);
  const setGrants = useSetPluginToolRowGrants(row.kind, row.id);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("tool.accessSettings")}</DialogTitle>
          <DialogDescription>{t("access:share.settingsDescription")}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <SharingSettings
            initiativeId={row.initiative_id}
            grants={row.grants}
            canShare={row.can.share}
            setGrants={setGrants}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
};

export const RowActions = ({
  table,
  row,
  language,
}: {
  table: ToolTable;
  row: ToolRow;
  language: string;
}) => {
  const { t } = useTranslation(["plugins", "common"]);
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const run = useRunPluginToolAction(table.kind);
  const [asking, setAsking] = useState<ToolActionDecl | null>(null);
  // The answers to its params, as the row would hold them.
  const [answers, setAnswers] = useState<ToolRow>(row);
  const [sharing, setSharing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const name = row.name || toolText(table.name, language);
  const isItem = table.parent !== null;
  const archived = row.archived_at !== null;
  const archive = useArchiveEntity({
    onSuccess: () => toast.success(t("common:toolSettings.archive.archived", { name })),
  });
  const unarchive = useUnarchiveEntity({
    onSuccess: () => toast.success(t("common:toolSettings.archive.unarchived", { name })),
  });
  const toggleArchive = archived ? unarchive : archive;
  const remove = useDeletePluginToolRow(table.kind, {
    onSuccess: () => {
      toast.success(t("common:toolSettings.deleted", { name }));
      setDeleting(false);
      // Back to what it was in: the row it is an item of, or its tool's list.
      void navigate({
        to: gp(
          table.parent !== null && row.parent_id !== null
            ? toolPluginRowRoute(row.initiative_id, table.parent, row.parent_id)
            : toolPluginListRoute(row.initiative_id, table.kind)
        ),
      });
    },
  });

  // Each as a built-in tool's item offers it: archiving is an edit, and the
  // way back out is its own answer while the tool it is in is archived, and
  // an edit while that tool is live and only the row is put away. An item is
  // deleted as it is changed, a tool's row by whoever may delete it.
  const declared = row.can.edit ? table.actions : [];
  const canShare = !isItem && row.can.share;
  const canArchive = archived ? row.can.unarchive || row.can.edit : row.can.edit;
  const canDelete = isItem ? row.can.contribute : row.can.delete;
  if (declared.length === 0 && !canShare && !canArchive && !canDelete) return null;

  const params = (asking?.params ?? []).flatMap((key) =>
    table.fields.filter((field) => field.key === key)
  );
  const go = (action: ToolActionDecl, onSuccess?: () => void) => {
    if (run.isPending) return;
    const given = (action.params ?? []).flatMap((key) =>
      table.fields
        .filter((field) => field.key === key)
        .map((field) => [field, fieldValue(answers, field)] as const)
    );
    run.mutate(
      { rowId: row.id, actionId: action.id, ...(given.length > 0 ? fieldChanges(given) : {}) },
      { onSuccess }
    );
  };
  const start = (action: ToolActionDecl) => {
    if (action.confirm || action.params?.length) {
      // Each param starts as a new row's field would.
      setAnswers(
        withChange(
          row,
          fieldChanges(
            table.fields
              .filter((field) => action.params?.includes(field.key))
              .map((field) => [field, fieldStart(table.fields, field)])
          )
        )
      );
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
          {declared.map((action) => (
            <DropdownMenuItem
              key={action.id}
              disabled={run.isPending}
              onSelect={() => start(action)}
            >
              {toolText(action.name, language)}
            </DropdownMenuItem>
          ))}
          {declared.length > 0 && (canShare || canArchive || canDelete) ? (
            <DropdownMenuSeparator />
          ) : null}
          {canShare ? (
            <DropdownMenuItem onSelect={() => setSharing(true)}>
              <Shield className="h-4 w-4" />
              {t("tool.accessSettings")}
            </DropdownMenuItem>
          ) : null}
          {canArchive ? (
            <DropdownMenuItem
              disabled={toggleArchive.isPending}
              onSelect={() => toggleArchive.mutate({ entityType: row.kind, entityId: row.id })}
            >
              {archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
              {t(
                archived
                  ? "common:toolSettings.archive.unarchive"
                  : "common:toolSettings.archive.archive"
              )}
            </DropdownMenuItem>
          ) : null}
          {canDelete ? (
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onSelect={() => setDeleting(true)}
            >
              <Trash2 className="h-4 w-4" />
              {t("common:delete")}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
      {canShare ? <AccessDialog open={sharing} onOpenChange={setSharing} row={row} /> : null}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("common:toolSettings.deleteConfirmTitle", { name })}
        description={t("common:toolSettings.deleteConfirmDescription")}
        confirmLabel={t("common:delete")}
        onConfirm={() => remove.mutate(row.id)}
        isLoading={remove.isPending}
        destructive
      />
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
                    onChange={(value) =>
                      setAnswers((held) => withChange(held, fieldChange(field, value)))
                    }
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

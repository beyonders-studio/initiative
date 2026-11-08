/**
 * The reader's home views as tabs, and — while customizing — what makes,
 * renames, copies, reorders and deletes them.
 *
 * Somebody with one view and no customizing going on sees no tabs at all: a
 * single tab is a label on a page that already has one.
 */

import { ArrowLeft, ArrowRight, Copy, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  canAddView,
  cleanViewName,
  type HomeViewEntry,
  type HomeViews,
  MAX_HOME_VIEWS,
  MAX_VIEW_NAME_LENGTH,
} from "@/lib/home/views";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Tabs, TabsBar, TabsTrigger } from "@/ui/tabs";

export interface HomeViewTabsProps {
  views: HomeViews;
  activeId: string;
  editing: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, name: string) => void;
  onDuplicate: (id: string) => void;
  onMove: (id: string, step: -1 | 1) => void;
  onDelete: (id: string) => void;
}

export function HomeViewTabs({
  views,
  activeId,
  editing,
  onSelect,
  onNew,
  onRename,
  onDuplicate,
  onMove,
  onDelete,
}: HomeViewTabsProps) {
  const { t } = useTranslation(["home", "common"]);
  const [renaming, setRenaming] = useState<HomeViewEntry | null>(null);
  const [deleting, setDeleting] = useState<HomeViewEntry | null>(null);

  if (views.views.length < 2 && !editing) return null;

  const index = views.views.findIndex((view) => view.id === activeId);
  const active = views.views[index];
  const roomForMore = canAddView(views);

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Tabs value={activeId} onValueChange={onSelect} className="min-w-0 flex-1">
        <TabsBar aria-label={t("views.label")}>
          {views.views.map((view) => (
            <TabsTrigger key={view.id} value={view.id} className="max-w-48">
              <span className="truncate">{view.name}</span>
            </TabsTrigger>
          ))}
        </TabsBar>
      </Tabs>

      {editing ? (
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-9"
            onClick={onNew}
            disabled={!roomForMore}
            aria-label={t("views.new")}
            title={roomForMore ? t("views.new") : t("views.limit", { max: MAX_HOME_VIEWS })}
          >
            <Plus className="size-4" />
          </Button>
          {active ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-9"
                  aria-label={t("views.menu", { name: active.name })}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setRenaming(active)}>
                  <Pencil className="size-4" /> {t("views.rename")}
                </DropdownMenuItem>
                <DropdownMenuItem disabled={!roomForMore} onSelect={() => onDuplicate(active.id)}>
                  <Copy className="size-4" /> {t("views.duplicate")}
                </DropdownMenuItem>
                <DropdownMenuItem disabled={index <= 0} onSelect={() => onMove(active.id, -1)}>
                  <ArrowLeft className="size-4" /> {t("views.moveLeft")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={index >= views.views.length - 1}
                  onSelect={() => onMove(active.id, 1)}
                >
                  <ArrowRight className="size-4" /> {t("views.moveRight")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={views.views.length < 2}
                  onSelect={() => setDeleting(active)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="size-4" /> {t("views.delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      ) : null}

      <RenameViewDialog
        view={renaming}
        onClose={() => setRenaming(null)}
        onSave={(name) => {
          if (renaming) onRename(renaming.id, name);
          setRenaming(null);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("views.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("views.deleteDescription")}
        confirmLabel={t("views.deleteConfirm")}
        destructive
        onConfirm={() => {
          if (deleting) onDelete(deleting.id);
          setDeleting(null);
        }}
      />
    </div>
  );
}

function RenameViewDialog({
  view,
  onClose,
  onSave,
}: {
  view: HomeViewEntry | null;
  onClose: () => void;
  onSave: (name: string) => void;
}) {
  return (
    <Dialog open={view !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby={undefined}>
        {/* Keyed by the view, so each opening starts from its current name. */}
        {view ? <RenameViewForm key={view.id} view={view} onSave={onSave} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function RenameViewForm({ view, onSave }: { view: HomeViewEntry; onSave: (name: string) => void }) {
  const { t } = useTranslation(["home", "common"]);
  const [name, setName] = useState(view.name);
  const clean = cleanViewName(name);
  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (clean) onSave(clean);
      }}
    >
      <DialogHeader>
        <DialogTitle>{t("views.renameTitle")}</DialogTitle>
      </DialogHeader>
      <Field label={t("views.nameLabel")}>
        <Input
          value={name}
          maxLength={MAX_VIEW_NAME_LENGTH}
          onChange={(event) => setName(event.target.value)}
          autoFocus
        />
      </Field>
      <DialogFooter submitLabel={t("common:save")} disabled={!clean} />
    </form>
  );
}

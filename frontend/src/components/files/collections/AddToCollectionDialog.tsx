import { useNavigate } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CollectionCreate,
  CollectionShapeEntry,
  CollectionShapeKey,
} from "@/api/generated/initiativeAPI.schemas";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import { ReadyMadeGallery } from "@/components/shared/ReadyMadeGallery";
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
import {
  useAddCollectionFiles,
  useCollectionShapes,
  useCollections,
  useCreateCollection,
} from "@/hooks/useCollections";
import { COLLECTION_ICON } from "@/lib/collections";
import { useCommunityPath } from "@/lib/communityUrl";
import { listFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import { collectionRoute } from "@/lib/tools";

interface AddToCollectionDialogProps {
  initiativeId: number;
  /** The files to put in, all of the initiative. */
  fileIds: number[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called once they are in, before the dialog closes. */
  onDone?: () => void;
}

/** Where a new collection starts: blank, a ready-made shape, or the shape of
 *  another of the initiative's collections. */
type Start =
  | { kind: "blank" }
  | { kind: "shape"; key: CollectionShapeKey }
  | { kind: "copy"; id: number };

/**
 * Put files in a collection: one of the initiative's the reader may change,
 * or a new one made of them. A collection is never made empty, so making one
 * is always making it of these files. A new one is named, then started blank,
 * as a ready-made shape (its lists and metadata), or with the shape of another
 * collection in the initiative.
 */
export const AddToCollectionDialog = ({
  initiativeId,
  fileIds,
  open,
  onOpenChange,
  onDone,
}: AddToCollectionDialogProps) => {
  const { t, i18n } = useTranslation(["files", "common"]);
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  // Choosing how a new one starts, once it is named.
  const [making, setMaking] = useState(false);
  const [start, setStart] = useState<Start>({ kind: "blank" });
  const collections = useCollections(open ? initiativeId : null);
  const all = collections.data?.items ?? [];
  const changeable = all.filter((collection) => collection.can.edit);
  const shapes = useCollectionShapes(open && making);

  const finish = () => {
    setName("");
    setMaking(false);
    setStart({ kind: "blank" });
    onDone?.();
    onOpenChange(false);
  };
  const create = useCreateCollection({
    onSuccess: (created) => {
      toast.success(t("collections.created", { name: created.name }));
      finish();
      void navigate({ to: gp(collectionRoute(created.initiative_id, created.id)) });
    },
  });

  const trimmed = name.trim();
  const submitNew = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed) return;
    if (!making) {
      setMaking(true);
      return;
    }
    const body: CollectionCreate = {
      initiative_id: initiativeId,
      name: trimmed,
      file_ids: fileIds,
    };
    if (start.kind === "shape") body.shape = start.key;
    if (start.kind === "copy") body.shape_from = start.id;
    create.mutate(body);
  };

  /** A glimpse of what a shape brings: the lists it shows, then its metadata. */
  const brings = (entry: CollectionShapeEntry) => {
    const lists = entry.lists.map((kind) => t(listLayoutLooks[kind].labelKey as never));
    const names = listFormat(i18n.language, { type: "conjunction" });
    return (
      <>
        <span className="mt-1 flex items-center gap-1" aria-hidden>
          {entry.lists.map((kind) => {
            const Icon = listLayoutLooks[kind].icon;
            return <Icon key={kind} className="h-3.5 w-3.5" />;
          })}
        </span>
        <span className="sr-only">
          {t("collections.shapes.lists", { lists: names.format(lists) })}
        </span>
        {entry.metadata.length > 0 ? (
          <span className="block">
            {t("collections.shapes.properties", {
              properties: names.format(entry.metadata.map((each) => each.name)),
            })}
          </span>
        ) : null}
      </>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-5 py-4">
          <DialogTitle>{t("collections.addTo")}</DialogTitle>
          <DialogDescription>
            {t("collections.addToDescription", { count: fileIds.length })}
          </DialogDescription>
        </DialogHeader>

        {making ? (
          <form onSubmit={submitNew} className="flex min-h-0 flex-1 flex-col">
            <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <div className="space-y-2">
                <Label htmlFor="new-collection-name">{t("collections.shapes.name")}</Label>
                <Input
                  id="new-collection-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={255}
                />
              </div>
              <ReadyMadeGallery
                blank={{
                  name: t("collections.shapes.blank"),
                  hint: t("collections.shapes.blankHint"),
                }}
                loading={shapes.isLoading}
                groups={(shapes.data ?? []).map((group) => ({
                  key: group.key,
                  name: group.name,
                  entries: group.entries.map((entry) => ({
                    key: entry.key,
                    name: entry.name,
                    hint: entry.hint,
                    brings: brings(entry),
                  })),
                }))}
                chosen={
                  start.kind === "blank" ? null : start.kind === "shape" ? start.key : undefined
                }
                onChoose={(entry) =>
                  setStart(
                    entry
                      ? { kind: "shape", key: entry.key as CollectionShapeKey }
                      : { kind: "blank" }
                  )
                }
              />
              {all.length > 0 ? (
                <div className="space-y-2">
                  <Label htmlFor="new-collection-shape-from">
                    {t("collections.shapes.copyLabel")}
                  </Label>
                  <Select
                    value={start.kind === "copy" ? String(start.id) : ""}
                    onValueChange={(value) => setStart({ kind: "copy", id: Number(value) })}
                  >
                    <SelectTrigger id="new-collection-shape-from">
                      <SelectValue placeholder={t("collections.shapes.copyPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {all.map((collection) => (
                        <SelectItem key={collection.id} value={String(collection.id)}>
                          {collection.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-muted-foreground text-xs">
                    {t("collections.shapes.copyHint")}
                  </p>
                </div>
              ) : null}
            </div>
            <DialogFooter className="border-t px-5 py-3">
              <Button type="button" variant="ghost" onClick={() => setMaking(false)}>
                {t("common:back")}
              </Button>
              <Button type="submit" disabled={!trimmed || create.isPending}>
                {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {t("collections.shapes.create")}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {changeable.length === 0 ? (
                <p className="px-3 py-2 text-muted-foreground text-sm">
                  {t("collections.noneToAddTo")}
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {changeable.map((collection) => (
                    <li key={collection.id}>
                      <AddToOne
                        collectionId={collection.id}
                        name={collection.name}
                        fileIds={fileIds}
                        onAdded={finish}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <form onSubmit={submitNew} className="flex items-center gap-2 border-t px-5 py-3">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("collections.namePlaceholder")}
                aria-label={t("collections.addToNew")}
                maxLength={255}
              />
              <Button type="submit" disabled={!trimmed} className="shrink-0">
                <Plus className="h-4 w-4" />
                {t("collections.addToNew")}
              </Button>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};

/** One collection to put the files in. */
const AddToOne = ({
  collectionId,
  name,
  fileIds,
  onAdded,
}: {
  collectionId: number;
  name: string;
  fileIds: number[];
  onAdded: () => void;
}) => {
  const { t } = useTranslation("files");
  const add = useAddCollectionFiles(collectionId, {
    onSuccess: () => {
      toast.success(t("collections.added", { count: fileIds.length, name }));
      onAdded();
    },
  });
  return (
    <Button
      variant="ghost"
      className="h-auto w-full justify-start px-3 py-2 text-left"
      disabled={add.isPending}
      onClick={() => add.mutate(fileIds)}
    >
      <COLLECTION_ICON className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{name}</span>
    </Button>
  );
};

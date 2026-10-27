import { useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAddCollectionFiles, useCollections, useCreateCollection } from "@/hooks/useCollections";
import { COLLECTION_ICON } from "@/lib/collections";
import { useCommunityPath } from "@/lib/communityUrl";
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

/**
 * Put files in a collection: one of the initiative's the reader may change,
 * or a new one made of them. A collection is never made empty, so making one
 * is always making it of these files.
 */
export const AddToCollectionDialog = ({
  initiativeId,
  fileIds,
  open,
  onOpenChange,
  onDone,
}: AddToCollectionDialogProps) => {
  const { t } = useTranslation(["files", "common"]);
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const collections = useCollections(open ? initiativeId : null);
  const changeable = (collections.data?.items ?? []).filter((collection) => collection.can.edit);

  const finish = () => {
    setName("");
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

  const submitNew = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate({ initiative_id: initiativeId, name: trimmed, file_ids: fileIds });
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
          <Button type="submit" disabled={!name.trim() || create.isPending} className="shrink-0">
            <Plus className="h-4 w-4" />
            {t("collections.addToNew")}
          </Button>
        </form>
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

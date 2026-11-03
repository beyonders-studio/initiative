import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { FileKind, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";
import { CollectionFilterField } from "@/components/files/collections/CollectionFilterField";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useFilesFeed } from "@/hooks/useFiles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { isToolEnabled } from "@/lib/tools";

/** A picture taken from Files: the address of the version picked, and the
 *  file's name, which starts as its alt text. */
export interface ChosenImage {
  src: string;
  name: string;
}

interface ImageChooserProps {
  /** The initiative it opens on: the one the picture is going into. Without
   *  one, the first the reader can open Files in. */
  initiativeId: number | null;
  onPick: (image: ChosenImage) => void;
  /** The address picked so far, shown chosen. */
  picked?: string | null;
}

/**
 * The pictures in Files, to put one somewhere: a page, a description, a
 * file's featured image.
 *
 * What goes in is the address of the version picked, a copy as it is now: a
 * newer version of the file does not change it, and nor does who the file is
 * shared with. A picture from another initiative is copied into the place it
 * goes when that is saved, as any picture pasted across initiatives is.
 */
export const ImageChooser = ({ initiativeId, onPick, picked = null }: ImageChooserProps) => {
  const { t } = useTranslation("files");
  const searchId = useId();
  const initiativeFieldId = useId();
  const initiativesQuery = useInitiatives();
  const initiatives = (initiativesQuery.data ?? []).filter((initiative) =>
    isToolEnabled(Tool.file, initiative)
  );
  const [chosenInitiative, setChosenInitiative] = useState<number | null>(null);
  const [collectionId, setCollectionId] = useState<number | undefined>(undefined);
  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query.trim());

  const opensOn = initiatives.find((initiative) => initiative.id === initiativeId)?.id;
  const shownInitiative = chosenInitiative ?? opensOn ?? initiatives[0]?.id ?? null;
  const feed = useFilesFeed(
    {
      initiative_id: shownInitiative,
      kind: FileKind.image,
      collection_id: collectionId,
      search: search || undefined,
    },
    { enabled: shownInitiative !== null }
  );
  const pictures = (feed.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((file) => file.file_url);

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        {initiatives.length > 1 && shownInitiative !== null ? (
          <div className="w-full space-y-2 sm:w-48">
            <Label
              htmlFor={initiativeFieldId}
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("columns.initiative")}
            </Label>
            <Select
              value={String(shownInitiative)}
              onValueChange={(next) => {
                setChosenInitiative(Number(next));
                // A collection is one initiative's.
                setCollectionId(undefined);
              }}
            >
              <SelectTrigger id={initiativeFieldId}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {initiatives.map((initiative) => (
                  <SelectItem key={initiative.id} value={String(initiative.id)}>
                    {initiative.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        {shownInitiative !== null ? (
          <CollectionFilterField
            value={{ collection_id: collectionId }}
            onChange={(next) => setCollectionId(next.collection_id ?? undefined)}
            initiativeId={shownInitiative}
          />
        ) : null}
        <div className="min-w-40 flex-1 space-y-2">
          <Label htmlFor={searchId} className="block font-medium text-muted-foreground text-xs">
            {t("filters.searchLabel")}
          </Label>
          <Input
            id={searchId}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("filters.searchFiles")}
          />
        </div>
      </div>

      <div className="max-h-[50vh] min-h-32 overflow-y-auto" aria-busy={feed.isFetching}>
        {pictures.length === 0 ? (
          initiativesQuery.isPending || (feed.isPending && shownInitiative !== null) ? null : (
            <p className="py-6 text-center text-muted-foreground text-sm">
              {t("imageChooser.none")}
            </p>
          )
        ) : (
          <div className="grid grid-cols-fill-24/6 gap-2">
            {pictures.map((file) => (
              <CollectionFileTile
                key={file.id}
                file={file}
                fit="square"
                selecting
                selected={picked !== null && picked === file.file_url}
                onActivate={() => onPick({ src: file.file_url ?? "", name: file.name })}
              />
            ))}
          </div>
        )}
        {feed.hasNextPage ? (
          <div className="flex justify-center pt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={feed.isFetchingNextPage}
              onClick={() => void feed.fetchNextPage()}
            >
              {t("imageChooser.more")}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
};

interface ImageChooserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initiativeId: number | null;
  /** Called with the picture picked; the dialog closes itself. */
  onPick: (image: ChosenImage) => void;
}

/** {@link ImageChooser} on its own, where a pick is the whole choice. */
export const ImageChooserDialog = ({
  open,
  onOpenChange,
  initiativeId,
  onPick,
}: ImageChooserDialogProps) => {
  const { t } = useTranslation("files");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("imageChooser.title")}</DialogTitle>
          <DialogDescription>{t("imageChooser.description")}</DialogDescription>
        </DialogHeader>
        {open ? (
          <ImageChooser
            initiativeId={initiativeId}
            onPick={(image) => {
              onPick(image);
              onOpenChange(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
};

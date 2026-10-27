import { Link } from "@tanstack/react-router";
import { ListPlus, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CollectionRead, FileRead } from "@/api/generated/initiativeAPI.schemas";
import { AddToCollectionButton } from "@/components/files/collections/AddToCollectionButton";
import { CollectionFileFields } from "@/components/files/collections/CollectionFileFields";
import { badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useCollectionFileFields, useCollections } from "@/hooks/useCollections";
import { useCommunityPath } from "@/lib/communityUrl";
import { collectionRoute } from "@/lib/tools";

/**
 * The collections a file is in, each a way to it, and the way to put it in
 * another. Only the collections the reader can see are named. Beside each
 * with fields of its own, the file's values of them, which whoever may
 * change the collection edits.
 */
export const FileCollections = ({
  file,
}: {
  file: Pick<FileRead, "id" | "initiative_id" | "collection_ids">;
}) => {
  const { t } = useTranslation("common");
  const gp = useCommunityPath();
  const collections = useCollections(file.collection_ids.length > 0 ? file.initiative_id : null);
  const named = (collections.data?.items ?? []).filter((collection) =>
    file.collection_ids.includes(collection.id)
  );

  return (
    <>
      {named.length > 0 ? (
        <span className="flex gap-1">
          {named.map((collection) => (
            <span key={collection.id} className="inline-flex items-center">
              <Link
                to={gp(collectionRoute(collection.initiative_id, collection.id))}
                className={badgeVariants({ variant: "secondary" })}
              >
                {collection.name}
              </Link>
              {collection.fields.length > 0 ? (
                <FieldsInCollection collection={collection} fileId={file.id} />
              ) : null}
            </span>
          ))}
        </span>
      ) : (
        <span className="text-muted-foreground">{t("toolChest.none")}</span>
      )}
      <AddToCollectionButton initiativeId={file.initiative_id} fileIds={[file.id]} />
    </>
  );
};

/** The file's values of one collection's fields, opened from beside its name. */
const FieldsInCollection = ({
  collection,
  fileId,
}: {
  collection: CollectionRead;
  fileId: number;
}) => {
  const { t } = useTranslation("files");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("collections.fields.of", { name: collection.name })}
        >
          <ListPlus className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <Values collection={collection} fileId={fileId} />
      </PopoverContent>
    </Popover>
  );
};

/** Read only once opened. */
const Values = ({ collection, fileId }: { collection: CollectionRead; fileId: number }) => {
  const { t } = useTranslation("files");
  const values = useCollectionFileFields(collection.id, fileId);
  if (values.isError) return <p className="text-destructive text-sm">{t("loadError")}</p>;
  if (!values.data) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  return (
    <CollectionFileFields collection={collection} file={{ id: fileId, fields: values.data }} />
  );
};

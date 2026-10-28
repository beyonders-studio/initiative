import { Link } from "@tanstack/react-router";
import { ListPlus } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  CollectionRead,
  FileRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { AddToCollectionButton } from "@/components/files/collections/AddToCollectionButton";
import { badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { collectionMetadataSaves, useCollections } from "@/hooks/useCollections";
import { useCommunityPath } from "@/lib/communityUrl";
import { PlacedPropertyField } from "@/lib/layouts/fieldEditors";
import { collectionRoute } from "@/lib/tools";

/**
 * The collections a file is in, each a way to it, and the way to put it in
 * another. Only the collections the reader can see are named. Beside each
 * with metadata of its own, the file's values of it, which whoever may
 * change the collection edits.
 */
export const FileCollections = ({
  file,
}: {
  file: Pick<FileRead, "id" | "initiative_id" | "collection_ids" | "properties">;
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
              {collection.metadata.length > 0 ? (
                <MetadataInCollection collection={collection} file={file} />
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

/** The file's values of one collection's metadata, opened from beside its
 *  name. */
const MetadataInCollection = ({
  collection,
  file,
}: {
  collection: CollectionRead;
  file: Pick<FileRead, "id" | "properties">;
}) => {
  const { t } = useTranslation("files");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("collections.properties.of", { name: collection.name })}
        >
          <ListPlus className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <Values collection={collection} fileId={file.id} properties={file.properties} />
      </PopoverContent>
    </Popover>
  );
};

/** Each saved on its own, from the values the file's read carries. Whoever may
 *  change the collection edits them; anyone else reads those that hold a
 *  value. */
const Values = ({
  collection,
  fileId,
  properties,
}: {
  collection: CollectionRead;
  fileId: number;
  properties: PropertySummary[];
}) => {
  const { t } = useTranslation("files");
  // One copy per read of the file, which a save's answer is held over.
  const values = useMemo(
    () => properties.filter((each) => each.collection_id === collection.id),
    [properties, collection.id]
  );
  return (
    <section aria-label={t("collections.properties.heading")} className="space-y-3">
      <h2 className="font-medium text-sm">{t("collections.properties.heading")}</h2>
      {collection.metadata.map((definition) => (
        <PlacedPropertyField
          key={definition.id}
          kind={collectionMetadataSaves(collection.id)}
          id={fileId}
          properties={values}
          readOnly={!collection.can.edit}
          initiativeId={collection.initiative_id}
          propertyId={definition.id}
          definitions={collection.metadata}
        />
      ))}
    </section>
  );
};

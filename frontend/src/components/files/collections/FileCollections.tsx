import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { FileRead } from "@/api/generated/initiativeAPI.schemas";
import { AddToCollectionButton } from "@/components/files/collections/AddToCollectionButton";
import { badgeVariants } from "@/components/ui/badge";
import { useCollections } from "@/hooks/useCollections";
import { useCommunityPath } from "@/lib/communityUrl";
import { collectionRoute } from "@/lib/tools";

/**
 * The collections a file is in, each a way to it, and the way to put it in
 * another. Only the collections the reader can see are named.
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
            <Link
              key={collection.id}
              to={gp(collectionRoute(collection.initiative_id, collection.id))}
              className={badgeVariants({ variant: "secondary" })}
            >
              {collection.name}
            </Link>
          ))}
        </span>
      ) : (
        <span className="text-muted-foreground">{t("toolChest.none")}</span>
      )}
      <AddToCollectionButton initiativeId={file.initiative_id} fileIds={[file.id]} />
    </>
  );
};

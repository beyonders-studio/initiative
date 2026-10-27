import { useTranslation } from "react-i18next";

import type { CollectionFileSummary, CollectionRead } from "@/api/generated/initiativeAPI.schemas";
import { collectionFieldSaves } from "@/hooks/useCollections";
import { PlacedPropertyField } from "@/lib/layouts/fieldEditors";

/**
 * A file's values of the collection's own fields, beside it where it is opened
 * from the collection, each saved on its own. Whoever may change the
 * collection edits them; anyone else reads those that hold a value.
 */
export const CollectionFileFields = ({
  collection,
  file,
}: {
  collection: CollectionRead;
  file: CollectionFileSummary;
}) => {
  const { t } = useTranslation("files");
  if (collection.fields.length === 0) return null;
  return (
    <section aria-label={t("collections.fields.heading")} className="space-y-3">
      <h2 className="font-medium text-sm">{t("collections.fields.heading")}</h2>
      {collection.fields.map((field) => (
        <PlacedPropertyField
          // Keyed by the file too: moving to the next picture starts afresh.
          key={`${file.id}:${field.id}`}
          kind={collectionFieldSaves(collection.id)}
          id={file.id}
          properties={file.fields}
          readOnly={!collection.can.edit}
          initiativeId={collection.initiative_id}
          propertyId={field.id}
          definitions={collection.fields}
        />
      ))}
    </section>
  );
};

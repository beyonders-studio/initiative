import { useTranslation } from "react-i18next";

import { CollectionCard } from "@/components/files/collections/CollectionCard";
import { useCollections } from "@/hooks/useCollections";

/**
 * The initiative's collections, a strip of cards above its files. Nothing at
 * all until there is one: a collection is made from files, so the way to the
 * first is selecting some below.
 */
export const CollectionsStrip = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation("files");
  const collections = useCollections(initiativeId).data?.items ?? [];
  if (collections.length === 0) return null;

  return (
    <section aria-labelledby="files-collections-heading" className="space-y-3">
      <h2 id="files-collections-heading" className="font-semibold text-lg">
        {t("collections.heading")}
      </h2>
      {/* Scrolls sideways rather than wrapping: the files are what the page
          is for, and a row of cards keeps them close. */}
      <ul className="-mx-1 flex snap-x gap-4 overflow-x-auto px-1 pb-2">
        {collections.map((collection) => (
          <li key={collection.id} className="w-56 shrink-0 snap-start">
            <CollectionCard collection={collection} />
          </li>
        ))}
      </ul>
    </section>
  );
};

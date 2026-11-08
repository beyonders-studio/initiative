import { useTranslation } from "react-i18next";

import { useCollections } from "@/hooks/useCollections";
import { CollectionCard } from "@/pages/community/tools/files/CollectionCard";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/ui/carousel";

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
      {/* A shelf rather than a grid that wraps: the files are what the page
          is for, and one row of cards keeps them close. The space under the
          cards is for their shadows, which the shelf's edge would cut off. */}
      <Carousel>
        <CarouselContent className="pb-2">
          {collections.map((collection) => (
            <CarouselItem key={collection.id} className="basis-60">
              <CollectionCard collection={collection} />
            </CarouselItem>
          ))}
        </CarouselContent>
        <CarouselPrevious />
        <CarouselNext />
      </Carousel>
    </section>
  );
};

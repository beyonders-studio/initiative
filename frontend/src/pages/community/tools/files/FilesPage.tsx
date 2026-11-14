import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCollections } from "@/hooks/useCollections";
import { ToolIndexPage } from "@/pages/community/tools/ToolIndexPage";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/ui/carousel";

import { CollectionCard } from "./CollectionCard";

/**
 * The initiative's collections, a strip of cards above its files. Nothing at
 * all until there is one: a collection is made from files, so the way to the
 * first is selecting some below.
 */
const CollectionsStrip = ({ initiativeId }: { initiativeId: number }) => {
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

type FilesViewProps = {
  /** The initiative this list belongs to. Required: files are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's files: its collections, then the files themselves as
 *  cards, a table, or browsed by tag. */
export const FilesView = (props: FilesViewProps) => (
  <div className="space-y-6">
    <CollectionsStrip initiativeId={props.fixedInitiativeId} />
    <ToolIndexPage tool={Tool.file} {...props} />
  </div>
);

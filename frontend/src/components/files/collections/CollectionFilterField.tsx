import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ToolListFilters } from "@/components/tools/ToolFilterFields";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCollections } from "@/hooks/useCollections";

/** "Any" is a sentinel: the underlying filter is absent, not a value. */
const ANY_COLLECTION = "any";

type CollectionFilterFieldProps = {
  value: ToolListFilters<typeof Tool.file>;
  onChange: (next: ToolListFilters<typeof Tool.file>) => void;
  initiativeId: number;
};

/** A files list narrowed to the files in one collection. Nothing while the
 *  initiative has none. */
export const CollectionFilterField = ({
  value,
  onChange,
  initiativeId,
}: CollectionFilterFieldProps) => {
  const { t } = useTranslation("files");
  const id = useId();
  const collections = useCollections(initiativeId).data?.items ?? [];
  if (collections.length === 0 && value.collection_id == null) return null;

  return (
    <div className="w-full space-y-2 sm:w-48">
      <Label htmlFor={id} className="block font-medium text-muted-foreground text-xs">
        {t("collections.filter")}
      </Label>
      <Select
        value={value.collection_id == null ? ANY_COLLECTION : String(value.collection_id)}
        onValueChange={(next) =>
          onChange({
            ...value,
            collection_id: next === ANY_COLLECTION ? undefined : Number(next),
          })
        }
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY_COLLECTION}>{t("collections.anyCollection")}</SelectItem>
          {collections.map((collection) => (
            <SelectItem key={collection.id} value={String(collection.id)}>
              {collection.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

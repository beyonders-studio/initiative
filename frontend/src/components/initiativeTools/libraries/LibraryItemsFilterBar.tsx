import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { TagPicker } from "@/components/tags/TagPicker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type ImageOrder = "newest" | "oldest";

interface LibraryItemsFilterBarProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  tags: TagSummary[];
  onTagsChange: (tags: TagSummary[]) => void;
  order: ImageOrder;
  onOrderChange: (order: ImageOrder) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  activeCount?: number;
  onClear?: () => void;
}

/** The wall's filters, in the panel every other tool list uses. */
export const LibraryItemsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  tags,
  onTagsChange,
  order,
  onOrderChange,
  filtersOpen,
  onFiltersOpenChange,
  activeCount,
  onClear,
}: LibraryItemsFilterBarProps) => {
  const { t } = useTranslation(["libraries", "tags"]);

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={onFiltersOpenChange}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 md:flex-1">
          <Label
            htmlFor="library-item-search"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.searchPicturesLabel")}
          </Label>
          <Input
            id="library-item-search"
            placeholder={t("filters.searchPictures")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            className="min-w-60"
          />
        </div>
        <div className="w-full space-y-2 sm:w-64">
          <Label
            htmlFor="library-item-tags"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("tags:picker.filterLabel")}
          </Label>
          <TagPicker
            id="library-item-tags"
            variant="filter"
            selectedTags={tags}
            onChange={onTagsChange}
            placeholder={t("tags:picker.anyTag")}
          />
        </div>
        <div className="w-full space-y-2 sm:w-44">
          <Label
            htmlFor="library-item-order"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.order")}
          </Label>
          <Select value={order} onValueChange={(value) => onOrderChange(value as ImageOrder)}>
            <SelectTrigger id="library-item-order">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">{t("filters.newestFirst")}</SelectItem>
              <SelectItem value="oldest">{t("filters.oldestFirst")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </ToolFilterPanel>
  );
};

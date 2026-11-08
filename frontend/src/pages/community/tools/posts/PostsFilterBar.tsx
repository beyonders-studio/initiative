import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterFields, type ToolFilterFieldsProps } from "@/components/tools/ToolFilterFields";
import { ToolFilterPanel } from "@/components/tools/ToolFilterPanel";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** What a board is showing: everything, or only what is still waiting. */
export type ReadFilter = "all" | "unread";

type PostsFilterBarProps = ToolFilterFieldsProps<typeof Tool.post> & {
  readFilter: ReadFilter;
  onReadFilterChange: (value: ReadFilter) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets every filter this bar owns — offered in the mobile sheet. */
  onClear?: () => void;
};

/**
 * The board's filters, in the panel every other tool list uses: the board's
 * shared fields, and the read state, which is the reader's own.
 */
export const PostsFilterBar = ({
  value,
  onChange,
  readFilter,
  onReadFilterChange,
  filtersOpen,
  onFiltersOpenChange,
  onClear,
  activeCount,
  initiativeId,
}: PostsFilterBarProps) => {
  const { t } = useTranslation(["posts", "common"]);

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={onFiltersOpenChange}
      onClear={onClear}
      activeCount={activeCount}
    >
      <ToolFilterFields
        tool={Tool.post}
        value={value}
        onChange={onChange}
        initiativeId={initiativeId}
      >
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="post-read-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.readState")}
          </Label>
          <Select
            value={readFilter}
            onValueChange={(next) => onReadFilterChange(next as ReadFilter)}
          >
            <SelectTrigger id="post-read-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("filters.allPosts")}</SelectItem>
              <SelectItem value="unread">{t("filters.unreadOnly")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </ToolFilterFields>
    </ToolFilterPanel>
  );
};

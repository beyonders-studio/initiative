import { Tag as TagIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { useCreateTag, useTags } from "@/hooks/useTags";
import { DEFAULT_COLOR } from "@/lib/initiativeColors";
import { Button, buttonVariants } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Combobox } from "@/ui/combobox";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";

import { TagBadge } from "./TagBadge";

const DEFAULT_TAG_COLORS = [
  DEFAULT_COLOR, // Indigo
  "#8B5CF6", // Violet
  "#EC4899", // Pink
  "#EF4444", // Red
  "#F97316", // Orange
  "#EAB308", // Yellow
  "#22C55E", // Green
  "#14B8A6", // Teal
  "#0EA5E9", // Sky
  "#6B7280", // Gray
];

interface TagPickerProps {
  /** Ties the trigger to a `<Label htmlFor>`. A `combobox` takes no accessible
   *  name from its own contents, so without this the control is unnamed. */
  id?: string;
  selectedTags: TagSummary[];
  onChange: (tags: TagSummary[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** "default" shows tag badges in trigger, "filter" matches Select styling */
  variant?: "default" | "filter";
}

export function TagPicker({
  id,
  selectedTags,
  onChange,
  placeholder,
  disabled = false,
  className,
  variant = "default",
}: TagPickerProps) {
  const { t } = useTranslation(["tags", "common"]);
  const resolvedPlaceholder = placeholder ?? t("picker.defaultPlaceholder");
  // The new tag's name while it is being made, in place of the list.
  const [newTagName, setNewTagName] = useState<string | null>(null);
  const [newTagColor, setNewTagColor] = useState(DEFAULT_TAG_COLORS[0]);

  const { data: allTags = [], isLoading } = useTags();
  const createTagMutation = useCreateTag();

  // The chosen tags as well as the community's: a tag made here is chosen
  // before the list has it.
  const tagsById = useMemo(
    () => new Map([...selectedTags, ...allTags].map((tag) => [String(tag.id), tag])),
    [selectedTags, allTags]
  );

  const startCreating = (name: string) => {
    setNewTagName(name);
    setNewTagColor(DEFAULT_TAG_COLORS[Math.floor(Math.random() * DEFAULT_TAG_COLORS.length)]);
  };

  const handleCreateTag = async () => {
    const name = newTagName?.trim();
    if (!name) return;
    try {
      const newTag = await createTagMutation.mutateAsync({ name, color: newTagColor });
      onChange([...selectedTags, { id: newTag.id, name: newTag.name, color: newTag.color }]);
      setNewTagName(null);
    } catch {
      // Error is handled by the mutation
    }
  };

  return (
    <Combobox
      multiple
      id={id}
      className={className}
      items={allTags.map((tag) => ({
        value: String(tag.id),
        label: tag.name,
        icon: <span className="h-3 w-3 rounded-full" style={{ backgroundColor: tag.color }} />,
      }))}
      value={selectedTags.map((tag) => String(tag.id))}
      onValueChange={(ids) =>
        onChange(
          ids.flatMap((tagId) => {
            const tag = tagsById.get(tagId);
            return tag ? [{ id: tag.id, name: tag.name, color: tag.color }] : [];
          })
        )
      }
      placeholder={resolvedPlaceholder}
      searchPlaceholder={t("picker.searchPlaceholder")}
      loading={isLoading}
      typedLabel={(typed) => typed && t("picker.createTag", { name: typed })}
      onCreate={startCreating}
      onOpenChange={(open) => {
        if (!open) setNewTagName(null);
      }}
      disabled={disabled}
      trigger={
        variant === "default" ? (
          // Rendered as a div, not a button: the selected tags carry their own
          // "remove" buttons, which may not be nested inside a <button>.
          <div
            id={id}
            // biome-ignore lint/a11y/useAriaPropsForRole: the popover's trigger, which this is rendered as, sets aria-expanded
            role="combobox"
            tabIndex={disabled ? -1 : 0}
            aria-disabled={disabled}
            onKeyDown={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.currentTarget.click();
              }
            }}
            className={cn(
              buttonVariants({ variant: "outline" }),
              "h-auto min-h-10 w-full cursor-pointer justify-start",
              disabled && "pointer-events-none opacity-50",
              selectedTags.length === 0 && "text-muted-foreground",
              className
            )}
          >
            <TagIcon className="h-4 w-4 shrink-0 opacity-50" />
            {selectedTags.length > 0 ? (
              <div className="flex min-w-0 flex-1 flex-wrap gap-1">
                {selectedTags.map((tag) => (
                  <TagBadge
                    key={tag.id}
                    tag={tag}
                    size="sm"
                    onRemove={() => onChange(selectedTags.filter((each) => each.id !== tag.id))}
                  />
                ))}
              </div>
            ) : (
              <span>{resolvedPlaceholder}</span>
            )}
          </div>
        ) : undefined
      }
    >
      {newTagName !== null ? (
        <div className="space-y-3 p-3">
          <div className="font-medium text-sm">{t("picker.createHeading")}</div>
          <Input
            placeholder={t("picker.namePlaceholder")}
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void handleCreateTag();
              }
            }}
            autoFocus
          />
          <ColorPickerPopover value={newTagColor} onChange={setNewTagColor} triggerLabel="Color" />
          <div className="flex gap-2">
            <Button
              size="sm"
              className="flex-1"
              onClick={() => void handleCreateTag()}
              disabled={!newTagName.trim() || createTagMutation.isPending}
            >
              {createTagMutation.isPending ? t("picker.creating") : t("picker.create")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setNewTagName(null)}>
              {t("common:cancel")}
            </Button>
          </div>
        </div>
      ) : null}
    </Combobox>
  );
}

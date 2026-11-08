import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { ItemFieldSave } from "@/hooks/useFieldSave";
import { FieldFrame, type ItemEdit } from "@/lib/layouts/editing";

import { TagBadgeList } from "./TagBadge";
import { TagPicker } from "./TagPicker";

/** An item's tags, saved the moment they are picked. Clearing them offers
 *  Undo. A reader who cannot change them sees the tags alone, and nothing
 *  where there are none. */
export const TagsField = <
  I extends { tags: TagSummary[] },
  P extends { tag_ids?: number[] | null },
>({
  label,
  tags,
  save,
  readOnly,
  placeholder,
}: {
  label: string;
  tags: TagSummary[];
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const edit = (picked: TagSummary[]): ItemEdit<I, P> => ({
    patch: { tag_ids: picked.map((tag) => tag.id) } as P,
    shows: { tags: picked } as Partial<I>,
  });
  if (readOnly) {
    return tags.length ? (
      <div className="space-y-2">
        <p className="font-medium text-sm">{label}</p>
        <TagBadgeList tags={tags} limit={tags.length} className="gap-2" />
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <TagPicker
        selectedTags={tags}
        onChange={(picked) =>
          void save.save(edit(picked), picked.length === 0 ? edit(tags) : undefined)
        }
        placeholder={placeholder}
      />
    </FieldFrame>
  );
};

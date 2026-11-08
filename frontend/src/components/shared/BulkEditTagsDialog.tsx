import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary, TagTarget } from "@/api/generated/initiativeAPI.schemas";
import { bulkEditTags } from "@/api/generated/tags/tags";
import { TagPicker } from "@/components/tags/TagPicker";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { DialogWithSuccessProps } from "@/types/dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/ui/tabs";

/** Any entity that has an `id` and optional `tags`. */
interface TaggableItem {
  id: number;
  tags?: TagSummary[] | null;
}

interface BulkEditTagsDialogProps<T extends TaggableItem> extends DialogWithSuccessProps {
  items: T[];
  /** Entity type for the server-side bulk endpoint. */
  targetType: TagTarget;
  communityId: number;
  /** Called after the bulk call succeeds to invalidate relevant caches. */
  onInvalidate: () => void;
}

/** Adding tags to, or taking them off, a selection of any taggable kind. */
export function BulkEditTagsDialog<T extends TaggableItem>({
  open,
  onOpenChange,
  ...props
}: BulkEditTagsDialogProps<T>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <BulkEditTagsForm onOpenChange={onOpenChange} {...props} />
      </DialogContent>
    </Dialog>
  );
}

// Drawn only while the dialog is open, so each opening starts on Add with no
// tags chosen.
function BulkEditTagsForm<T extends TaggableItem>({
  onOpenChange,
  items,
  targetType,
  communityId,
  onInvalidate,
  onSuccess,
}: Omit<BulkEditTagsDialogProps<T>, "open">) {
  const { t } = useTranslation("common");
  const count = items.length;
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [tagsToAdd, setTagsToAdd] = useState<TagSummary[]>([]);
  const [tagsToRemove, setTagsToRemove] = useState<TagSummary[]>([]);
  const [isPending, setIsPending] = useState(false);

  const existingTags = useMemo(() => {
    const tagMap = new Map<number, TagSummary>();
    for (const item of items) {
      for (const tag of item.tags ?? []) {
        if (!tagMap.has(tag.id)) {
          tagMap.set(tag.id, tag);
        }
      }
    }
    return Array.from(tagMap.values());
  }, [items]);

  const handleApply = useCallback(async () => {
    if (mode === "add" && tagsToAdd.length === 0) return;
    if (mode === "remove" && tagsToRemove.length === 0) return;

    setIsPending(true);
    try {
      // One atomic server-side call: adds/removals are computed against
      // current DB state, so a stale client cache can't corrupt the merge,
      // and a mid-batch failure can't leave items half-edited.
      await bulkEditTags(communityId, {
        target_type: targetType,
        target_ids: items.map((item) => item.id),
        add_tag_ids: mode === "add" ? tagsToAdd.map((tag) => tag.id) : [],
        remove_tag_ids: mode === "remove" ? tagsToRemove.map((tag) => tag.id) : [],
      });
      toast.success(
        mode === "add" ? t("bulkTags.tagsAdded", { count }) : t("bulkTags.tagsRemoved", { count })
      );

      onInvalidate();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(getErrorMessage(error, "common:bulkTags.updateError"));
    } finally {
      setIsPending(false);
    }
  }, [
    mode,
    tagsToAdd,
    tagsToRemove,
    items,
    count,
    targetType,
    communityId,
    onInvalidate,
    onOpenChange,
    onSuccess,
    t,
  ]);

  const canApply = mode === "add" ? tagsToAdd.length > 0 : tagsToRemove.length > 0;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("bulkTags.title")}</DialogTitle>
        <DialogDescription>
          {mode === "add"
            ? t("bulkTags.descriptionAdd", { count })
            : t("bulkTags.descriptionRemove", { count })}
        </DialogDescription>
      </DialogHeader>

      <Tabs value={mode} onValueChange={(v) => setMode(v as "add" | "remove")}>
        <TabsBar>
          <TabsTrigger value="add">{t("bulkTags.tabAdd")}</TabsTrigger>
          <TabsTrigger value="remove">{t("bulkTags.tabRemove")}</TabsTrigger>
        </TabsBar>

        <TabsContent value="add" className="mt-4">
          <TagPicker
            selectedTags={tagsToAdd}
            onChange={setTagsToAdd}
            placeholder={t("bulkTags.addPlaceholder")}
          />
        </TabsContent>

        <TabsContent value="remove" className="mt-4">
          {existingTags.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("bulkTags.noTags")}</p>
          ) : (
            <TagPicker
              selectedTags={tagsToRemove}
              onChange={(tags) =>
                setTagsToRemove(tags.filter((tag) => existingTags.some((e) => e.id === tag.id)))
              }
              placeholder={t("bulkTags.removePlaceholder")}
            />
          )}
        </TabsContent>
      </Tabs>

      <DialogFooter
        submitLabel={t("bulkTags.apply")}
        onSubmit={() => void handleApply()}
        pending={isPending}
        pendingLabel={t("bulkTags.applying")}
        disabled={!canApply}
      />
    </>
  );
}

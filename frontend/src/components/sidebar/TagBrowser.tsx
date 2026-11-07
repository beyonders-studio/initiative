import { Link } from "@tanstack/react-router";
import { CircleChevronRight, Pencil, Trash2 } from "lucide-react";
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary, TagRead as TagType } from "@/api/generated/initiativeAPI.schemas";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteTag, useUpdateTag } from "@/hooks/useTags";
import { communityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { getItem, setItem } from "@/lib/storage";
import { buildTagTree, type TagTreeNode } from "@/lib/tagTree";
import { cn } from "@/lib/utils";

// Maximum visual indentation depth (children still render, just don't indent further)
const MAX_TAG_INDENT = 3;

/**
 * When present, the tag tree renders in edit mode: each tag row exposes a
 * selection checkbox plus rename/delete affordances instead of a navigation
 * link. A `null` value means normal, navigable mode.
 */
interface TagEditContextValue {
  selectedIds: Set<number>;
  toggleSelect: (id: number) => void;
  onEditTag: (tag: TagSummary) => void;
  onDeleteTag: (tag: TagSummary) => void;
}

const TagEditContext = createContext<TagEditContextValue | null>(null);

export interface TagBrowserProps {
  tags: TagType[];
  isLoading: boolean;
  activeCommunityId: number | null;
  /** Changing this value re-syncs the open/closed state from storage. */
  collapseKey?: number;
  /** Edit mode is controlled by the sidebar header's pencil toggle. */
  editMode?: boolean;
  /** Select-all also expands every group so the selection is visible. */
  onExpandAll?: () => void;
}

export const TagBrowser = ({
  tags,
  isLoading,
  activeCommunityId,
  collapseKey,
  editMode = false,
  onExpandAll,
}: TagBrowserProps) => {
  const { t } = useTranslation(["tags", "nav", "common"]);
  const tagTree = useMemo(() => buildTagTree(tags), [tags]);

  const updateTag = useUpdateTag();
  const deleteTag = useDeleteTag();
  // Bulk path: per-delete success toasts are suppressed in favor of the
  // single summary toast below (per-tag error toasts still fire).
  const bulkDeleteTag = useDeleteTag({ silent: true });

  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());

  // Leaving edit mode discards the selection.
  if (!editMode && selectedIds.size > 0) {
    setSelectedIds(new Set());
  }

  // Rename + recolor dialog state.
  const [renameTag, setRenameTag] = useState<TagSummary | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

  // Delete confirmation state (single row and bulk).
  const [deleteTarget, setDeleteTarget] = useState<TagSummary | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const allSelected = tags.length > 0 && selectedIds.size === tags.length;

  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(tags.map((tag) => tag.id)));
    // Expand every group so the nested selections are visible.
    onExpandAll?.();
  }, [allSelected, tags, onExpandAll]);

  const openRename = useCallback((tag: TagSummary) => {
    setRenameTag(tag);
    setEditName(tag.name);
    setEditColor(tag.color);
  }, []);

  const closeRename = useCallback(() => {
    setRenameTag(null);
    setEditName("");
    setEditColor("");
  }, []);

  const handleSaveRename = useCallback(async () => {
    if (!renameTag || !editName.trim()) return;
    try {
      await updateTag.mutateAsync({
        tagId: renameTag.id,
        data: { name: editName.trim(), color: editColor },
      });
      closeRename();
    } catch {
      // Error surfaced by the mutation.
    }
  }, [renameTag, editName, editColor, updateTag, closeRename]);

  const handleSingleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    const { id } = deleteTarget;
    try {
      await deleteTag.mutateAsync(id);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } catch {
      // Error surfaced by the mutation.
    }
    setDeleteTarget(null);
  }, [deleteTarget, deleteTag]);

  const handleBulkDelete = useCallback(async () => {
    const ids = Array.from(selectedIds);
    let deleted = 0;
    let failed = 0;
    // Small N, sequential — the shared delete mutation refreshes the caches
    // for each removal; we roll the outcome up into a single summary toast.
    for (const id of ids) {
      try {
        await bulkDeleteTag.mutateAsync(id);
        deleted += 1;
      } catch {
        failed += 1;
      }
    }
    setBulkDeleteOpen(false);
    setSelectedIds(new Set());
    if (failed > 0) {
      toast.error(t("manage.bulkDeleteError"));
    } else {
      toast.success(t("manage.bulkDeleted", { count: deleted }));
    }
  }, [selectedIds, bulkDeleteTag, t]);

  const editContextValue = useMemo<TagEditContextValue | null>(
    () =>
      editMode
        ? {
            selectedIds,
            toggleSelect,
            onEditTag: openRename,
            onDeleteTag: setDeleteTarget,
          }
        : null,
    [editMode, selectedIds, toggleSelect, openRename]
  );

  if (isLoading) {
    return (
      <div className="space-y-2 px-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (tags.length === 0) {
    return <div className="px-4 py-2 text-muted-foreground text-sm">{t("nav:noTagsCreated")}</div>;
  }

  const selectedCount = selectedIds.size;

  return (
    <div className="space-y-1">
      {editMode && (
        <div className="flex items-center justify-between gap-1">
          <Checkbox
            checked={allSelected ? true : selectedCount > 0 ? "indeterminate" : false}
            onCheckedChange={toggleSelectAll}
            aria-label={t("manage.selectAll")}
            className="ml-1"
          />
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-destructive text-xs hover:bg-destructive/10 hover:text-destructive"
            disabled={selectedCount === 0 || deleteTag.isPending}
            onClick={() => setBulkDeleteOpen(true)}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {t("manage.deleteSelected", { count: selectedCount })}
          </Button>
        </div>
      )}

      <TagEditContext.Provider value={editContextValue}>
        <div className="space-y-1">
          {tagTree.map((node) => (
            <TagTreeNodeComponent
              key={node.fullPath}
              node={node}
              depth={0}
              activeCommunityId={activeCommunityId}
              collapseKey={collapseKey}
            />
          ))}
        </div>
      </TagEditContext.Provider>

      {/* Rename + recolor dialog */}
      <Dialog open={renameTag !== null} onOpenChange={(open) => !open && closeRename()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("manage.editTagTitle")}</DialogTitle>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder={t("picker.namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleSaveRename();
                }
              }}
              autoFocus
              className="min-w-0 flex-1"
            />
            <ColorPickerPopover
              value={editColor}
              onChange={setEditColor}
              triggerLabel={t("manage.color")}
              className="h-9 w-auto shrink-0"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeRename}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={() => void handleSaveRename()}
              disabled={!editName.trim() || updateTag.isPending}
            >
              {updateTag.isPending ? t("detail.saving") : t("detail.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Single-tag delete confirmation */}
      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("detail.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("detail.deleteDescription", { name: deleteTarget?.name ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleSingleDelete()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("detail.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk delete confirmation */}
      <AlertDialog open={bulkDeleteOpen} onOpenChange={setBulkDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("manage.bulkDeleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("manage.bulkDeleteDescription", { count: selectedCount })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleBulkDelete()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("detail.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

interface EditableTagRowProps {
  tag: TagSummary;
  label: string;
  count?: number;
  bold?: boolean;
  edit: TagEditContextValue;
}

/** A tag row in edit mode: select checkbox, color dot, rename + delete. */
const EditableTagRow = ({ tag, label, count, bold, edit }: EditableTagRowProps) => {
  const { t } = useTranslation("tags");
  const checked = edit.selectedIds.has(tag.id);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1.5 text-sm">
      <Checkbox
        checked={checked}
        onCheckedChange={() => edit.toggleSelect(tag.id)}
        aria-label={t("manage.selectTag", { name: tag.name })}
        className="shrink-0"
      />
      <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: tag.color }} />
      <span className={cn("min-w-0 flex-1 truncate", bold && "font-medium")}>{label}</span>
      {count !== undefined && (
        <span className="shrink-0 text-muted-foreground text-xs">{count}</span>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0"
        onClick={() => edit.onEditTag(tag)}
        aria-label={t("manage.editTag", { name: tag.name })}
      >
        <Pencil className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0 text-muted-foreground hover:text-destructive"
        onClick={() => edit.onDeleteTag(tag)}
        aria-label={t("manage.deleteTag", { name: tag.name })}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
};

interface TagTreeNodeComponentProps {
  node: TagTreeNode;
  depth: number;
  activeCommunityId: number | null;
  collapseKey?: number;
}

const TagTreeNodeComponent = memo(
  ({ node, depth, activeCommunityId, collapseKey }: TagTreeNodeComponentProps) => {
    const { t } = useTranslation("nav");
    const edit = useContext(TagEditContext);
    // Helper to create community-scoped paths
    const gp = (path: string) =>
      activeCommunityId ? communityPath(activeCommunityId, path) : path;
    const [isOpen, setIsOpen] = useState(() => {
      try {
        const stored = getItem("tag-group-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<string, boolean>;
          return states[node.fullPath] ?? false;
        }
      } catch {
        // Ignore parsing errors
      }
      return false;
    });

    useEffect(() => {
      try {
        const stored = getItem("tag-group-collapsed-states");
        const states = stored ? (JSON.parse(stored) as Record<string, boolean>) : {};
        states[node.fullPath] = isOpen;
        setItem("tag-group-collapsed-states", JSON.stringify(states));
      } catch {
        // Ignore storage errors
      }
    }, [isOpen, node.fullPath]);

    // Re-sync from storage when collapseKey changes (collapse/expand all)
    useEffect(() => {
      if (collapseKey === undefined) return;
      try {
        const stored = getItem("tag-group-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<string, boolean>;
          setIsOpen(states[node.fullPath] ?? false);
        } else {
          setIsOpen(false);
        }
      } catch {
        // Ignore parsing errors
      }
    }, [collapseKey, node.fullPath]);

    const hasChildren = node.children.length > 0;
    const canExpand = hasChildren;

    // Get color from this node's tag, or first descendant with a tag
    const getNodeColor = (n: TagTreeNode): string | undefined => {
      if (n.tag?.color) return n.tag.color;
      for (const child of n.children) {
        const color = getNodeColor(child);
        if (color) return color;
      }
      return undefined;
    };
    const nodeColor = getNodeColor(node);

    // Count all descendant tags (for display)
    const countDescendants = (n: TagTreeNode): number => {
      let count = 0;
      for (const child of n.children) {
        if (child.tag) count++;
        count += countDescendants(child);
      }
      return count;
    };
    const descendantCount = countDescendants(node);

    // Leaf node (no children) - simple clickable item
    if (!hasChildren) {
      if (!node.tag) return null; // Ghost node with no tag and no children
      if (edit) {
        return <EditableTagRow tag={node.tag} label={node.segment} edit={edit} />;
      }
      return (
        <Link
          to={gp(`/tags/${node.tag.id}`)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
        >
          <span
            className="h-3 w-3 shrink-0 rounded-full"
            style={{ backgroundColor: node.tag.color }}
          />
          <span className="min-w-0 flex-1 truncate">{node.segment}</span>
        </Link>
      );
    }

    // Node with children - collapsible
    return (
      <Collapsible open={isOpen} onOpenChange={canExpand ? setIsOpen : undefined}>
        <div className="flex items-center">
          {canExpand ? (
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                aria-label={isOpen ? t("collapse") : t("expand")}
              >
                <CircleChevronRight
                  className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                  style={{ color: nodeColor || undefined }}
                />
              </Button>
            </CollapsibleTrigger>
          ) : (
            <span className="flex h-7 w-7 shrink-0 items-center justify-center">
              <span
                className="h-3 w-3 rounded-full"
                style={{ backgroundColor: nodeColor || undefined }}
              />
            </span>
          )}
          {node.tag ? (
            edit ? (
              <EditableTagRow
                tag={node.tag}
                label={node.segment}
                count={descendantCount}
                bold
                edit={edit}
              />
            ) : (
              <Link
                to={gp(`/tags/${node.tag.id}`)}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1.5 text-sm transition-colors hover:bg-accent"
              >
                <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
                <span className="shrink-0 text-muted-foreground text-xs">{descendantCount}</span>
              </Link>
            )
          ) : (
            <span className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1.5 text-sm">
              <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
              <span className="shrink-0 text-muted-foreground text-xs">{descendantCount}</span>
            </span>
          )}
        </div>
        {canExpand && isOpen && (
          <CollapsibleContent
            className={cn("space-y-0.5 border-l pl-2", depth < MAX_TAG_INDENT && "ml-3")}
            style={{ borderColor: nodeColor || undefined }}
            forceMount
          >
            {node.children.map((child) => (
              <TagTreeNodeComponent
                key={child.fullPath}
                node={child}
                depth={depth + 1}
                activeCommunityId={activeCommunityId}
                collapseKey={collapseKey}
              />
            ))}
          </CollapsibleContent>
        )}
      </Collapsible>
    );
  }
);
TagTreeNodeComponent.displayName = "TagTreeNodeComponent";

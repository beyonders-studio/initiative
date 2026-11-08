import { ChevronRight, CircleOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { getItem, setItem } from "@/lib/storage";
import { buildTagTree, countFilesForNode, type TagTreeNode } from "@/lib/tagTree";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { ScrollArea } from "@/ui/scroll-area";

export const UNTAGGED_PATH = "__untagged__";

const EXPANDED_STORAGE_KEY = "files:tag-tree-expanded";
const MAX_INDENT = 3;

function loadExpandedState(): Record<string, boolean> {
  try {
    const stored = getItem(EXPANDED_STORAGE_KEY);
    if (stored) return JSON.parse(stored) as Record<string, boolean>;
  } catch {
    // ignore
  }
  return {};
}

function saveExpandedState(state: Record<string, boolean>) {
  try {
    setItem(EXPANDED_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

interface TagTreeViewProps {
  tags: TagSummary[];
  tagCounts: Record<number, number>;
  /** Offers "Not tagged" with this count; left off for a list that cannot be
   *  narrowed to the untagged. */
  untaggedCount?: number | null;
  selectedTagPaths: Set<string>;
  onToggleTag: (fullPath: string, ctrlKey: boolean) => void;
}

export const TagTreeView = ({
  tags,
  tagCounts,
  untaggedCount,
  selectedTagPaths,
  onToggleTag,
}: TagTreeViewProps) => {
  const { t } = useTranslation("tags");
  const tagTree = useMemo(() => buildTagTree(tags), [tags]);

  const docCountByTagId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const [tagId, count] of Object.entries(tagCounts)) {
      counts.set(Number(tagId), count);
    }
    return counts;
  }, [tagCounts]);

  const [expandedState, setExpandedState] = useState<Record<string, boolean>>(loadExpandedState);

  useEffect(() => {
    saveExpandedState(expandedState);
  }, [expandedState]);

  const toggleExpanded = (fullPath: string) => {
    setExpandedState((prev) => ({ ...prev, [fullPath]: !prev[fullPath] }));
  };

  if (tags.length === 0) {
    return (
      <ScrollArea className="h-full">
        <div className="space-y-0.5 p-2">
          {untaggedCount != null ? (
            <button
              type="button"
              onClick={(e) => onToggleTag(UNTAGGED_PATH, e.ctrlKey || e.metaKey)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                "hover:bg-accent",
                selectedTagPaths.has(UNTAGGED_PATH) && "bg-accent"
              )}
            >
              <CircleOff className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-left">{t("tree.notTagged")}</span>
              <span className="shrink-0 text-muted-foreground text-xs">{untaggedCount}</span>
            </button>
          ) : null}
        </div>
      </ScrollArea>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-0.5 p-2">
        {tagTree.map((node) => (
          <TagTreeFilterNode
            key={node.fullPath}
            node={node}
            depth={0}
            docCountByTagId={docCountByTagId}
            selectedTagPaths={selectedTagPaths}
            expandedState={expandedState}
            onToggleExpand={toggleExpanded}
            onToggleTag={onToggleTag}
          />
        ))}
        {untaggedCount != null ? (
          <>
            <div className="my-1 border-muted border-t" />
            <button
              type="button"
              onClick={(e) => onToggleTag(UNTAGGED_PATH, e.ctrlKey || e.metaKey)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                "hover:bg-accent",
                selectedTagPaths.has(UNTAGGED_PATH) && "bg-accent"
              )}
            >
              <CircleOff className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-left">{t("tree.notTagged")}</span>
              <span className="shrink-0 text-muted-foreground text-xs">{untaggedCount}</span>
            </button>
          </>
        ) : null}
      </div>
    </ScrollArea>
  );
};

interface TagTreeFilterNodeProps {
  node: TagTreeNode;
  depth: number;
  docCountByTagId: Map<number, number>;
  selectedTagPaths: Set<string>;
  expandedState: Record<string, boolean>;
  onToggleExpand: (fullPath: string) => void;
  onToggleTag: (fullPath: string, ctrlKey: boolean) => void;
}

const TagTreeFilterNode = ({
  node,
  depth,
  docCountByTagId,
  selectedTagPaths,
  expandedState,
  onToggleExpand,
  onToggleTag,
}: TagTreeFilterNodeProps) => {
  const { t } = useTranslation("tags");
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedState[node.fullPath] ?? false;
  const isSelected = selectedTagPaths.has(node.fullPath);
  const docCount = countFilesForNode(node, docCountByTagId);

  const getNodeColor = (n: TagTreeNode): string | undefined => {
    if (n.tag?.color) return n.tag.color;
    for (const child of n.children) {
      const color = getNodeColor(child);
      if (color) return color;
    }
    return undefined;
  };
  const nodeColor = getNodeColor(node);

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    onToggleTag(node.fullPath, e.ctrlKey || e.metaKey);
  };

  // Leaf node
  if (!hasChildren) {
    if (!node.tag) return null;
    return (
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
          "hover:bg-accent",
          isSelected && "bg-accent"
        )}
      >
        <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: nodeColor }} />
        <span className="min-w-0 flex-1 truncate text-left">{node.segment}</span>
        <span className="shrink-0 text-muted-foreground text-xs">{docCount}</span>
      </button>
    );
  }

  // Node with children
  return (
    <div>
      <div className="flex items-center">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(node.fullPath);
          }}
          aria-label={isExpanded ? t("tree.collapse") : t("tree.expand")}
        >
          <ChevronRight
            className={cn("h-4 w-4 transition-transform", isExpanded && "rotate-90")}
            style={{ color: nodeColor || undefined }}
          />
        </Button>
        <button
          type="button"
          onClick={handleClick}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1.5 text-sm transition-colors",
            "hover:bg-accent",
            isSelected && "bg-accent"
          )}
        >
          <span className="min-w-0 flex-1 truncate text-left font-medium">{node.segment}</span>
          <span className="shrink-0 text-muted-foreground text-xs">{docCount}</span>
        </button>
      </div>
      {isExpanded && (
        <div
          className={cn("space-y-0.5 border-l pl-2", depth < MAX_INDENT && "ml-3")}
          style={{ borderColor: nodeColor || undefined }}
        >
          {node.children.map((child) => (
            <TagTreeFilterNode
              key={child.fullPath}
              node={child}
              depth={depth + 1}
              docCountByTagId={docCountByTagId}
              selectedTagPaths={selectedTagPaths}
              expandedState={expandedState}
              onToggleExpand={onToggleExpand}
              onToggleTag={onToggleTag}
            />
          ))}
        </div>
      )}
    </div>
  );
};

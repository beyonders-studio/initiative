import { Navigate, useNavigate, useParams, useRouter, useSearch } from "@tanstack/react-router";
import { SearchX, Settings, TagIcon, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagLoadError, TagToolTab, toolTabCount } from "@/components/tags/TagToolTab";
import { useDeleteTag, useTag, useTagCounts, useUpdateTag } from "@/hooks/useTags";
import {
  TOOL_ICONS,
  TOOLS,
  toolForRouteSegment,
  toolNavLabelKey,
  toolRouteSegment,
} from "@/lib/tools";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Input } from "@/ui/input";
import { TableSkeleton, TagDetailSkeleton } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/ui/tabs";

export const TagDetailPage = () => {
  const { t } = useTranslation(["tags", "common", "nav"]);
  const { tagId: tagIdParam } = useParams({ strict: false }) as { tagId: string };
  const parsedTagId = Number(tagIdParam);
  const hasValidTagId = Number.isFinite(parsedTagId) && parsedTagId > 0;
  const tagId = hasValidTagId ? parsedTagId : null;

  const router = useRouter();
  const navigate = useNavigate();
  const { tool: toolSegment } = useSearch({ strict: false }) as { tool?: string };

  const { data: tag, isLoading: tagLoading, error: tagError } = useTag(tagId);
  const { data: tagCounts, isError: countsFailed, refetch: refetchCounts } = useTagCounts(tagId);
  const deleteTagMutation = useDeleteTag();
  const updateTagMutation = useUpdateTag();

  const [isEditing, setIsEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

  // Reset edit state when navigating between tags
  const [prevTagId, setPrevTagId] = useState(tagId);
  if (prevTagId !== tagId) {
    setPrevTagId(tagId);
    setIsEditing(false);
    setEditName("");
    setEditColor("");
  }

  if (!hasValidTagId) {
    return <Navigate to="/" replace />;
  }

  if (tagLoading) {
    return <TagDetailSkeleton />;
  }

  if (tagError || !tag) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo="/"
        backLabel={t("detail.backToTags")}
      />
    );
  }

  const handleStartEdit = () => {
    setEditName(tag.name);
    setEditColor(tag.color);
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditName("");
    setEditColor("");
  };

  const handleSaveEdit = async () => {
    if (!editName.trim()) return;

    try {
      await updateTagMutation.mutateAsync({
        tagId: tag.id,
        data: {
          name: editName.trim(),
          color: editColor,
        },
      });
      setIsEditing(false);
    } catch {
      // Error handled by mutation
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTagMutation.mutateAsync(tag.id);
      router.navigate({ to: "/" });
    } catch {
      // Error handled by mutation
    }
  };

  const counts = tagCounts?.counts ?? {};
  const totalCount = Object.values(counts).reduce((sum, count) => sum + count, 0);
  // One tab per tool holding something with this tag — its own rows or what
  // is inside it, so a tagged task opens the Projects tab.
  const groups = TOOLS.map((tool) => ({ tool, count: toolTabCount(tool, counts) })).filter(
    ({ count }) => count > 0
  );
  const requested = toolSegment ? toolForRouteSegment(toolSegment) : null;
  const selected = groups.find(({ tool }) => tool === requested)?.tool ?? groups[0]?.tool ?? null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <TagIcon className="h-8 w-8 shrink-0" style={{ color: tag.color }} />
          <div>
            {isEditing ? (
              <div className="flex items-center gap-2">
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="h-9 w-64"
                  autoFocus
                />
                <ColorPickerPopover value={editColor} onChange={setEditColor} />
                <Button
                  size="sm"
                  onClick={() => void handleSaveEdit()}
                  disabled={!editName.trim() || updateTagMutation.isPending}
                >
                  {updateTagMutation.isPending ? t("detail.saving") : t("detail.save")}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleCancelEdit}>
                  {t("common:cancel")}
                </Button>
              </div>
            ) : (
              <>
                <h1 className="font-semibold text-3xl tracking-tight">{tag.name}</h1>
                <p className="text-muted-foreground text-sm">
                  {t("detail.taggedItems", { count: totalCount })}
                </p>
              </>
            )}
          </div>
        </div>

        {!isEditing && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleStartEdit}>
              <Settings className="h-4 w-4" />
              {t("detail.edit")}
            </Button>
            <Button variant="destructive" size="sm" onClick={() => setConfirmingDelete(true)}>
              <Trash2 className="h-4 w-4" />
              {t("detail.delete")}
            </Button>
            <ConfirmDialog
              open={confirmingDelete}
              onOpenChange={setConfirmingDelete}
              title={t("detail.deleteTitle")}
              description={t("detail.deleteDescription", { name: tag.name })}
              confirmLabel={t("detail.delete")}
              destructive
              onConfirm={() => void handleDelete()}
            />
          </div>
        )}
      </div>

      {!tagCounts && countsFailed ? (
        <TagLoadError onRetry={() => void refetchCounts()} />
      ) : !tagCounts ? (
        <TableSkeleton rows={6} columns={5} />
      ) : selected === null ? (
        <p className="text-muted-foreground text-sm">{t("detail.empty")}</p>
      ) : (
        <Tabs
          value={selected}
          onValueChange={(value) =>
            void navigate({
              to: ".",
              search: { tool: toolRouteSegment(value as Tool) },
              replace: true,
            })
          }
          className="space-y-4"
        >
          <TabsBar>
            {groups.map(({ tool, count }) => {
              const Icon = TOOL_ICONS[tool];
              return (
                <TabsTrigger key={tool} value={tool} className="inline-flex items-center gap-2">
                  <Icon className="h-4 w-4" />
                  {t("detail.toolTab", {
                    tool: t(toolNavLabelKey(tool), { ns: "nav" }),
                    count,
                  })}
                </TabsTrigger>
              );
            })}
          </TabsBar>
          {groups.map(({ tool }) => (
            <TabsContent key={tool} value={tool}>
              <TagToolTab tool={tool} tagId={tag.id} counts={counts} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
};

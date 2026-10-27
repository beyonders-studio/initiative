import { useNavigate, useParams } from "@tanstack/react-router";
import { MoreHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { PostPinButton } from "@/components/initiativeTools/posts/PostPinButton";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { DetailHeaderSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { usePost, useUpdatePost } from "@/hooks/usePosts";
import { detailLayoutOf, sharedTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { usePluginMenuActions } from "@/lib/layouts/plugins";
import { POST_DETAIL } from "@/lib/layouts/postLayout";
import { toast } from "@/lib/mascotToast";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

/**
 * One notice, on its own page — where its comments and reactions live, laid
 * out as its initiative lays out every notice.
 *
 * Its title, tags and properties are its tool's, in the header. Pinning sits
 * beside them but answers to a different rule: initiative management, not
 * write access, so an author can edit their own notice without being able to
 * lift it above everyone else's.
 */
export function PostDetailPage() {
  const { t } = useTranslation(["posts", "common"]);
  const { postId } = useParams({ strict: false }) as { postId: string };
  const parsedId = Number(postId);
  const gp = useCommunityPath();
  const postQuery = usePost(Number.isFinite(parsedId) ? parsedId : null);
  const post = postQuery.data;
  const initiativeId = useCanonicalInitiativeId(post?.initiative_id);
  useReadOnOpen(Tool.post, post?.id);
  useRecordOpen(Tool.post, post?.id);
  const canEdit = Boolean(post?.can.edit);
  const initiativeQuery = useInitiative(post?.initiative_id ?? null);
  const canPin = Boolean(initiativeQuery.data?.can.manage);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);
  const navigate = useNavigate();
  const rename = useUpdatePost(parsedId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });
  // Every notice in the initiative shares one layout.
  const layouts = useToolLayouts(post ? sharedTarget(Tool.post, post.initiative_id) : null);
  const pluginActions = usePluginMenuActions("post", parsedId, post?.initiative_id);

  if (!Number.isFinite(parsedId) || postQuery.isError) {
    return (
      <ToolAccessStatus
        error={postQuery.error}
        keys="posts:"
        backTo={gp(toolListRoute(Tool.post, initiativeId))}
        backLabel={t("backToPosts")}
        entity={{ kind: "post", id: parsedId }}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      {post ? (
        <ToolPageHeader
          tool={Tool.post}
          initiativeId={post.initiative_id}
          starId={post.id}
          settingsTo={canEdit ? toolSettingsRoute(Tool.post, initiativeId, post.id) : undefined}
          chest={
            <ToolChest tool={Tool.post} entity={post}>
              {canPin ? (
                <ToolChestSegment>
                  <PostPinButton post={post} labelled />
                </ToolChestSegment>
              ) : null}
            </ToolChest>
          }
          title={post.name}
          onRename={canEdit ? (name) => rename.mutateAsync({ name }) : undefined}
          titleExtras={
            <div className="flex items-center gap-1">
              <ReportButton targetType="post" targetId={post.id} authorId={post.created_by} />
              {/* Taken down or held, the notice is gone, so the reader goes
                  back to the board. */}
              <ModerationMenu
                targetType="post"
                targetId={post.id}
                canModerate={canModerate}
                reactable
                communityId={post.community_id}
                onGone={() => void navigate({ to: gp(toolListRoute(Tool.post, initiativeId)) })}
              />
              {pluginActions.items.length > 0 ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      aria-label={t("common:toolbar.moreActions")}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">{pluginActions.items}</DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </div>
          }
        />
      ) : (
        <DetailHeaderSkeleton actions={0} description={false} />
      )}
      {post ? (
        <DetailLayoutView
          detail={POST_DETAIL}
          item={post}
          layout={detailLayoutOf(layouts.data, "post") as StoredRegions | null}
          context={{ canEdit, canPin }}
        />
      ) : (
        <Skeleton className="h-40 w-full" />
      )}
      {pluginActions.dialog}
    </div>
  );
}

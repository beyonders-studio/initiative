import { ActorKind, type PostRead } from "@/api/generated/initiativeAPI.schemas";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserName } from "@/components/user/UserHandle";
import { useActorName } from "@/hooks/useActorName";
import { cn } from "@/ui/lib/utils";
import { RelativeTime } from "@/ui/relative-time";

/**
 * Who said it, and when. A notice is somebody saying something, and a board
 * that shows only what was said makes every notice read as the app's own
 * announcement. Stacked above the headline on the board; `inline` under the
 * title on the notice's own page, where the title comes first.
 */
export const PostByline = ({ post, inline = false }: { post: PostRead; inline?: boolean }) => {
  const actorName = useActorName();
  const when = (
    <RelativeTime
      date={post.published_at ?? post.created_at}
      className={cn("text-muted-foreground text-xs", !inline && "block")}
    />
  );
  if (post.created_by_kind !== ActorKind.member) {
    // A plug-in or Initiative posted it: named, with no picture of a person.
    return (
      <div className={cn("min-w-0", inline && "flex items-center gap-2")}>
        <span className="truncate font-medium text-sm">
          {actorName(post.created_by_kind, post.created_by_install)}
        </span>
        {when}
      </div>
    );
  }
  if (!post.author) return null;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <ProfileAvatar
        user={post.author}
        decorations={post.author.profile_decorations}
        presence={post.author.presence}
        className={cn("shrink-0", inline ? "size-7" : "size-8")}
      />
      {inline ? (
        <>
          <UserName user={post.author} className="text-sm" nameClassName="min-w-0 truncate" />
          <span aria-hidden className="text-muted-foreground text-xs">
            ·
          </span>
          {when}
        </>
      ) : (
        <div className="min-w-0">
          <UserName
            user={post.author}
            className="font-medium text-sm"
            nameClassName="min-w-0 truncate"
          />
          {when}
        </div>
      )}
    </div>
  );
};

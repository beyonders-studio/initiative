import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useInitiativeSharing } from "@/hooks/useModeration";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor, isSearchEntityType } from "@/lib/entityResolver";
import { Badge } from "@/ui/badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

/**
 * Who can reach what, across the initiative.
 *
 * Read-only, and deliberately: changing sharing goes through the resource's own
 * control, which is the one editor for it and the one that is tested. What this
 * adds is the overview — how widely each thing is reached — so finding the one
 * shared too far does not mean opening all of them.
 */
export const SharingArea = ({
  communityId,
  initiativeId,
}: {
  communityId: number;
  initiativeId: number;
}) => {
  const { t } = useTranslation(["moderation", "common"]);
  const { data, isLoading, isError, refetch } = useInitiativeSharing(communityId, initiativeId);
  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={5} avatar={false} />
      </SkeletonRegion>
    );
  }
  // A read that failed and a community that has shared nothing are different
  // answers; this says which one it is.
  if (isError) {
    return <StatusMessage onRetry={refetch} />;
  }

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("sharing.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("sharing.empty")}</p>
        ) : (
          items.map((item) => {
            const refType = isSearchEntityType(item.resource_type)
              ? entityRefTypeFor(item.resource_type)
              : null;
            const label = item.name || `${item.resource_type} ${item.resource_id}`;
            return (
              <div
                key={`${item.resource_type}-${item.resource_id}`}
                className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
              >
                <span className="min-w-0 truncate text-sm">
                  {refType ? (
                    <Link
                      to={communityPath(communityId, `/go/${refType}/${item.resource_id}`)}
                      className="underline-offset-4 hover:underline"
                    >
                      {label}
                    </Link>
                  ) : (
                    label
                  )}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {item.all_initiative_members && (
                    <Badge variant="secondary">{t("sharing.everyone")}</Badge>
                  )}
                  {/* Two counts, two keys: one string cannot pluralise on two
                      numbers at once. */}
                  <span className="text-muted-foreground text-sm">
                    {t("sharing.people", { count: item.user_grant_count })} ·{" "}
                    {t("sharing.roles", { count: item.role_grant_count })}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
};

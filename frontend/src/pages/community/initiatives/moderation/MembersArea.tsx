import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useInitiativeRoster } from "@/hooks/useInitiatives";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { StatusMessage } from "@/ui/status-message";

/** How many members the roster area shows at once. */
const MEMBERS_PAGE_SIZE = 50;

/**
 * The initiative's roster, with each member's role.
 *
 * Read-only. Who is in an initiative and what they may do is the initiative's
 * own settings to change; this is here so a moderator deciding a report can see
 * who they are deciding about without leaving the page.
 */
export const MembersArea = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useInitiativeRoster(initiativeId, {
    page,
    page_size: MEMBERS_PAGE_SIZE,
  });
  const members = data?.items ?? [];

  if (isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={5} avatar={false} />
      </SkeletonRegion>
    );
  }
  if (isError) {
    return <StatusMessage onRetry={refetch} />;
  }

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("members.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {members.map((member) => (
          <div
            key={member.user.id}
            className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
          >
            <span className="min-w-0 truncate text-sm">{getUserDisplayName(member.user)}</span>
            <div className="flex items-center gap-2">
              {member.override_share_restrictions && (
                <Badge variant="secondary">{t("members.fullAccess")}</Badge>
              )}
              <span className="text-muted-foreground text-sm">
                {member.role_display_name ?? t("members.noRole")}
              </span>
            </div>
          </div>
        ))}
        {data && (
          <PaginationBar
            className="pt-2"
            page={data.page}
            pageSize={data.page_size}
            totalCount={data.total_count}
            hasNext={data.has_next}
            onPageChange={setPage}
          />
        )}
      </CardContent>
    </Card>
  );
};

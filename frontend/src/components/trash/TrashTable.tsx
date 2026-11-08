import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EntityType, TrashItem } from "@/api/generated/initiativeAPI.schemas";
import {
  useCommunityTrashList,
  useMyTrashList,
  usePurgeTrashEntity,
  useRestoreTrashEntity,
} from "@/hooks/useTrash";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { RelativeTime } from "@/ui/relative-time";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

/**
 * `user` — the viewer's own deletions across every community (personal settings).
 * `community` — everything in the active community's trash (community-admin settings).
 */
type TrashVariant = "user" | "community";

/** Rows per page. */
const TRASH_PAGE_SIZE = 25;

interface TrashTableProps {
  variant: TrashVariant;
  // Whether to show the admin-only "Delete now" column. The backend also
  // gates this; the column is hidden so non-admins don't see a button that
  // would always 403.
  showPurgeAction: boolean;
}

export const TrashTable = ({ variant, showPurgeAction }: TrashTableProps) => {
  const { t } = useTranslation("trash");
  // Hooks must run unconditionally; pick the active query by variant. The
  // unused one is disabled so it never fires a request.
  const [page, setPage] = useState(1);
  const params = { page, page_size: TRASH_PAGE_SIZE };
  const myTrash = useMyTrashList(params, { enabled: variant === "user" });
  const communityTrash = useCommunityTrashList(params, { enabled: variant === "community" });
  const { data, isLoading } = variant === "user" ? myTrash : communityTrash;

  // Restoring or purging the last row of the last page leaves that page empty;
  // step back to the one before rather than showing nothing.
  const pastTheEnd = data !== undefined && data.items.length === 0 && data.page > 1;
  useEffect(() => {
    if (pastTheEnd) setPage((current) => Math.max(1, current - 1));
  }, [pastTheEnd]);

  const [purgeConfirm, setPurgeConfirm] = useState<
    | { open: false }
    | {
        open: true;
        communityId: number;
        entityType: EntityType;
        entityId: number;
        name: string;
      }
  >({ open: false });

  const restoreMutation = useRestoreTrashEntity({
    onSuccess: () => {
      toast.success(t("restoreSuccess"));
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "trash:restoreError"));
    },
  });

  const purgeMutation = usePurgeTrashEntity({
    onSuccess: () => {
      toast.success(t("purgeSuccess"));
      setPurgeConfirm({ open: false });
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "trash:purgeError"));
    },
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  if (isLoading) {
    return (
      <SkeletonRegion>
        <TableSkeleton rows={4} columns={4} toolbar={false} />
      </SkeletonRegion>
    );
  }

  if (!data || data.total_count === 0) {
    return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  }

  const handleRestoreClick = (item: TrashItem) => {
    restoreMutation.mutate({
      communityId: item.community_id,
      entityType: item.entity_type,
      entityId: item.entity_id,
    });
  };

  const handlePurgeConfirm = () => {
    if (!purgeConfirm.open) return;
    purgeMutation.mutate({
      communityId: purgeConfirm.communityId,
      entityType: purgeConfirm.entityType,
      entityId: purgeConfirm.entityId,
    });
  };

  return (
    <>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("columnType")}</TableHead>
              <TableHead>{t("columnName")}</TableHead>
              <TableHead>{t("columnDeletedBy")}</TableHead>
              <TableHead>{t("columnDeletedAt")}</TableHead>
              <TableHead>{t("columnPurgeAt")}</TableHead>
              <TableHead className="text-right">{t("columnActions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.entity_type}-${item.entity_id}`}>
                <TableCell>
                  <Badge variant="secondary">{t(`entityType.${item.entity_type}` as const)}</Badge>
                </TableCell>
                <TableCell className="font-medium">{item.name || `#${item.entity_id}`}</TableCell>
                <TableCell className="text-muted-foreground">{item.deleted_by_display}</TableCell>
                <TableCell className="text-muted-foreground">
                  <RelativeTime date={item.deleted_at} fallback={item.deleted_at} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {item.purge_at ? (
                    <RelativeTime date={item.purge_at} fallback={item.purge_at} />
                  ) : (
                    t("neverPurges")
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleRestoreClick(item)}
                      disabled={restoreMutation.isPending}
                    >
                      {t("restoreButton")}
                    </Button>
                    {showPurgeAction && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() =>
                          setPurgeConfirm({
                            open: true,
                            communityId: item.community_id,
                            entityType: item.entity_type,
                            entityId: item.entity_id,
                            name: item.name || `#${item.entity_id}`,
                          })
                        }
                        disabled={purgeMutation.isPending}
                      >
                        {t("deleteNowButton")}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PaginationBar
        className="mt-4"
        page={data.page}
        pageSize={data.page_size}
        totalCount={data.total_count}
        hasNext={data.has_next}
        onPageChange={setPage}
      />

      {purgeConfirm.open && (
        <ConfirmDialog
          open={purgeConfirm.open}
          onOpenChange={(open) => !open && setPurgeConfirm({ open: false })}
          title={t("deleteNowConfirmTitle")}
          description={t("deleteNowConfirmDescription", {
            type: t(`entityType.${purgeConfirm.entityType}` as const).toLowerCase(),
          })}
          confirmLabel={t("deleteNowConfirmAction")}
          onConfirm={handlePurgeConfirm}
          isLoading={purgeMutation.isPending}
          destructive
        />
      )}
    </>
  );
};

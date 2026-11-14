import { useTranslation } from "react-i18next";

import type { AccessGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { UserHandle } from "@/components/user/UserHandle";
import {
  flattenGrants,
  useAccessGrantQueue,
  useApproveAccessGrant,
  useDenyAccessGrant,
  useRevokeAccessGrant,
} from "@/hooks/useAccessGrants";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { minutesLeft } from "@/ui/lib/formatDate";
import { LoadMore } from "@/ui/load-more";

import { communityLabel, GrantCaseMark, grantScope } from "./grantForm";

// Always surface the community id alongside the name so approvers can
// disambiguate similarly-named communities (and fall back cleanly when the name
// isn't populated).
/** Who holds a grant: their handle, or their account number where the
 *  account is gone. Never their address. */
const GrantHolder = ({ grant }: { grant: AccessGrantRead }) =>
  grant.user ? <UserHandle user={grant.user} /> : <>{getUserDisplayName({ id: grant.user_id })}</>;

export const ApprovalQueue = () => {
  const { t } = useTranslation(["settings", "common"]);
  const pending = useAccessGrantQueue("pending");
  // Server-side ``live`` filter so paging the active list is accurate (no
  // client-side is_live filtering that would leave pages partially empty).
  const active = useAccessGrantQueue("approved", { live: true });
  const pendingItems = flattenGrants(pending.data?.pages);
  const activeItems = flattenGrants(active.data?.pages);

  const approve = useApproveAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.approved")),
  });
  const deny = useDenyAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.denied")),
  });
  const revoke = useRevokeAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.revoked")),
  });

  return (
    <SettingsSection
      title={t("accessGrants.queueTitle")}
      description={t("accessGrants.queueDescription")}
      contentClassName="space-y-5"
    >
      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.pendingHeading")}</h3>
        {!pendingItems.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noPending")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {pendingItems.map((grant) => (
              <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="truncate text-sm">
                    <GrantHolder grant={grant} /> → {communityLabel(grant)} · {grantScope(grant)} ·{" "}
                    {t("accessGrants.minutes", { minutes: grant.requested_duration_minutes })}
                  </p>
                  <p className="flex gap-2 text-muted-foreground text-xs">
                    <GrantCaseMark grant={grant} />
                    <span className="truncate">{grant.reason}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => approve.mutate({ grantId: grant.id })}
                    disabled={approve.isPending}
                  >
                    {t("accessGrants.approve")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => deny.mutate(grant.id)}
                    disabled={deny.isPending}
                  >
                    {t("accessGrants.deny")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={pending.hasNextPage}
          loading={pending.isFetchingNextPage}
          onLoadMore={pending.fetchNextPage}
        />
      </div>

      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.activeHeading")}</h3>
        {!activeItems.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noActive")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {activeItems.map((grant) => {
              const left = minutesLeft(grant.expires_at);
              return (
                <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      <GrantHolder grant={grant} /> → {communityLabel(grant)} · {grantScope(grant)}
                    </p>
                    {(left !== null || grant.case_task_id != null) && (
                      <p className="flex gap-2 text-muted-foreground text-xs">
                        <GrantCaseMark grant={grant} />
                        {left !== null && (
                          <span>{t("accessGrants.expiresIn", { minutes: left })}</span>
                        )}
                      </p>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => revoke.mutate(grant.id)}
                    disabled={revoke.isPending}
                  >
                    {t("accessGrants.revoke")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={active.hasNextPage}
          loading={active.isFetchingNextPage}
          onLoadMore={active.fetchNextPage}
        />
      </div>
    </SettingsSection>
  );
};

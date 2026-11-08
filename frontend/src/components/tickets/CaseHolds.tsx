/**
 * What is held on an operations case, for the platform moderators working it.
 *
 * Holds live in the community the content is in, so they are read there,
 * under the reader's `moderate` grant on that community. Without one there is
 * nothing to show but how to get one. With one, each hold can be released —
 * back as it was, to the trash, or destroyed — and the reported content can be
 * held from here.
 */
import { Link } from "@tanstack/react-router";
import { Lock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ContentHoldRead,
  HoldRelease,
  type HoldRelease as HoldReleaseValue,
} from "@/api/generated/initiativeAPI.schemas";
import { HoldDialog } from "@/components/moderation/HoldDialog";
import { useCaseHolds, useReleaseHold } from "@/hooks/useHolds";
import { Button } from "@/ui/button";
import { CardContent } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";

interface CaseHoldsProps {
  taskId: number;
  /** The community the case is about. */
  communityId: number;
  /** What the case is about in it, where it names one thing. */
  resourceType?: string | null;
  resourceId?: number | null;
}

const HoldRow = ({ hold, communityId }: { hold: ContentHoldRead; communityId: number }) => {
  const { t } = useTranslation("intake");
  const placed = useRelativeTime(hold.placed_at);
  const [purging, setPurging] = useState(false);
  const release = useReleaseHold(communityId, { onSuccess: () => setPurging(false) });
  const open = hold.released_at == null;
  const releaseAs = (outcome: HoldReleaseValue) => release.mutate({ holdId: hold.id, outcome });

  return (
    <li className="space-y-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium text-sm">
          {hold.label ?? t("case.holds.target", { type: hold.target_type, id: hold.target_id })}
        </p>
        <p className="text-muted-foreground text-xs">
          {t(`case.holds.via.${hold.placed_via}`)} · {placed}
        </p>
      </div>
      <p className="text-sm">
        {t(`case.holds.reasons.${hold.reason}`)}
        {hold.legal_basis ? ` · ${t(`case.holds.bases.${hold.legal_basis}`)}` : null}
      </p>
      {hold.note ? (
        <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">{hold.note}</p>
      ) : null}
      {open ? (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={release.isPending}
            onClick={() => releaseAs(HoldRelease.restore)}
          >
            {t("case.holds.restore")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={release.isPending}
            onClick={() => releaseAs(HoldRelease.remove)}
          >
            {t("case.holds.remove")}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={release.isPending}
            onClick={() => setPurging(true)}
          >
            {t("case.holds.purge")}
          </Button>
          <ConfirmDialog
            open={purging}
            onOpenChange={setPurging}
            title={t("case.holds.purgeTitle")}
            description={t("case.holds.purgeDescription")}
            confirmLabel={t("case.holds.purge")}
            destructive
            isLoading={release.isPending}
            onConfirm={() => releaseAs(HoldRelease.purge)}
          />
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">
          {t(`case.holds.released.${hold.release_outcome ?? HoldRelease.restore}`)}
        </p>
      )}
    </li>
  );
};

export const CaseHolds = ({ taskId, communityId, resourceType, resourceId }: CaseHoldsProps) => {
  const { t } = useTranslation("intake");
  const holds = useCaseHolds(communityId, taskId);
  const [holding, setHolding] = useState(false);

  if (holds.isLoading) return null;
  const items = holds.data ?? [];
  const canHoldReported =
    holds.isSuccess &&
    resourceType != null &&
    resourceId != null &&
    !items.some(
      (hold) =>
        hold.released_at == null &&
        hold.target_type === resourceType &&
        hold.target_id === resourceId
    );

  return (
    <CardContent className="space-y-3 border-t pt-4">
      <p className="flex items-center gap-2 font-medium text-sm">
        <Lock className="h-4 w-4" aria-hidden="true" />
        {t("case.holds.title")}
      </p>
      {holds.isError ? (
        <p className="text-muted-foreground text-sm">
          {t("case.holds.needGrant", { community: communityId })}{" "}
          <Link
            to="/settings/operator/access"
            // Reading what the platform holds takes Moderate.
            search={{ form: "request", case: taskId, community: communityId, level: "moderate" }}
            className="underline underline-offset-2"
          >
            {t("case.holds.requestAccess")}
          </Link>
        </p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("case.holds.none")}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((hold) => (
            <HoldRow key={hold.id} hold={hold} communityId={communityId} />
          ))}
        </ul>
      )}
      {canHoldReported ? (
        <>
          <Button size="sm" variant="outline" onClick={() => setHolding(true)}>
            {t("case.holds.holdReported")}
          </Button>
          <HoldDialog
            open={holding}
            onOpenChange={setHolding}
            communityId={communityId}
            targetType={resourceType}
            targetId={resourceId}
            caseTaskId={taskId}
          />
        </>
      ) : null}
    </CardContent>
  );
};

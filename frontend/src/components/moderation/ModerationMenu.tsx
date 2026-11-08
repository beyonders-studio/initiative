/**
 * A moderator's actions on one thing, wherever it is shown.
 *
 * Offered to the moderation set of the thing's initiative — its community's
 * admins and the people with Full access there — and to nobody else: the
 * caller passes whether this reader is one, from what the server already
 * said about them (`initiative.can.moderate`, a thread's `can_moderate`).
 * The server refuses the rest anyway.
 *
 * - **Remove…** takes it down, with a reason its author is told.
 * - **Warn…** tells its author it crossed a line, in the moderator's words,
 *   and leaves it up.
 * - **Clear reactions**, for things people react to.
 * - **Hold for the platform** keeps it exactly as it is, out of everyone's
 *   sight, the moderator's included, until the platform releases it.
 *
 * Locking a thread is not here: it is on the thread itself, wherever one is
 * shown (`CommentSection`).
 */
import { Shield } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ModerationAct } from "@/api/generated/initiativeAPI.schemas";
import { HoldDialog } from "@/components/moderation/HoldDialog";
import { RemovalDialog } from "@/components/moderation/RemovalDialog";
import { WarnDialog } from "@/components/moderation/WarnDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useModerate } from "@/hooks/useModeration";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

export interface ModerationMenuProps {
  /** A `SearchEntityType` value, and which one. */
  targetType: string;
  targetId: number;
  /** Whether this reader moderates the thing's initiative. Nothing renders
   *  otherwise. */
  canModerate: boolean;
  /** Whether people react to it. */
  reactable?: boolean;
  /** Defaults to the community the reader is standing in. */
  communityId?: number | null;
  /** Once it has been taken down or held — to close the sheet it was opened
   *  from, say. */
  onGone?: () => void;
  className?: string;
}

export const ModerationMenu = ({
  targetType,
  targetId,
  canModerate,
  reactable = false,
  communityId,
  onGone,
  className,
}: ModerationMenuProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const activeCommunityId = useActiveCommunityId();
  const community = communityId ?? activeCommunityId ?? 0;
  const [removing, setRemoving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [holding, setHolding] = useState(false);
  const [warning, setWarning] = useState(false);
  const act = useModerate(community);

  if (!canModerate || !community) return null;

  const target = { target_type: targetType, target_id: targetId };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={className}
            aria-label={t("menu.label")}
          >
            <Shield className="h-4 w-4" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>{t("menu.label")}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setRemoving(true)}>{t("menu.remove")}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setWarning(true)}>{t("menu.warn")}</DropdownMenuItem>
          {reactable && (
            <DropdownMenuItem onSelect={() => setClearing(true)}>
              {t("menu.clearReactions")}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-destructive" onSelect={() => setHolding(true)}>
            {t("menu.hold")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <RemovalDialog
        open={removing}
        onOpenChange={setRemoving}
        targetType={targetType}
        pending={act.isPending}
        onConfirm={({ reason, note }) =>
          act.mutate(
            { ...target, act: ModerationAct.remove, reason, note },
            {
              onSuccess: () => {
                setRemoving(false);
                toast.success(t("remove.done"));
                onGone?.();
              },
            }
          )
        }
      />
      <WarnDialog
        open={warning}
        onOpenChange={setWarning}
        pending={act.isPending}
        onConfirm={(message) =>
          act.mutate(
            { ...target, act: ModerationAct.warn, note: message },
            {
              onSuccess: () => {
                setWarning(false);
                toast.success(t("warn.done"));
              },
            }
          )
        }
      />
      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("menu.clearTitle")}
        description={t("menu.clearDescription")}
        confirmLabel={t("menu.clearReactions")}
        destructive
        isLoading={act.isPending}
        onConfirm={() =>
          act.mutate(
            { ...target, act: ModerationAct.clear_reactions },
            {
              onSuccess: () => {
                setClearing(false);
                toast.success(t("menu.cleared"));
              },
            }
          )
        }
      />
      <HoldDialog
        open={holding}
        onOpenChange={setHolding}
        communityId={community}
        targetType={targetType}
        targetId={targetId}
        onHeld={onGone}
      />
    </>
  );
};

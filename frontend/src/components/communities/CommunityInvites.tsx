import { Copy, Trash2 } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CommunityInviteRead, SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { HelpLink } from "@/components/support/HelpLink";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import type { InviteLinkLimits, useCommunityInvites } from "@/hooks/useCommunityInvites";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";

const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

/** The two limits every invite link takes: how many may use it, and for how long. */
export const InviteLimitFields = ({
  idPrefix,
  value,
  onChange,
}: {
  idPrefix: string;
  value: InviteLinkLimits;
  onChange: (value: InviteLinkLimits) => void;
}) => {
  const { t } = useTranslation("communities");
  return (
    <>
      <Field label={t("users.maxUsesLabel")}>
        <Input
          type="number"
          min={1}
          value={value.maxUses}
          onChange={(event) => onChange({ ...value, maxUses: Number(event.target.value) })}
        />
      </Field>
      <Field label={t("users.expiresDaysLabel")}>
        <Input
          type="number"
          min={0}
          value={value.expiresDays}
          onChange={(event) => onChange({ ...value, expiresDays: Number(event.target.value) })}
        />
      </Field>
    </>
  );
};

/** The link of an invite just made, with a copy button. Its code is shown this once. */
export const NewInviteLink = ({ code }: { code: string }) => {
  const { t } = useTranslation("communities");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteLinkForCode(code));
      toast.success(t("users.inviteLinkCopied"));
    } catch (error) {
      console.error(error);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-primary/40 bg-primary/5 p-4 text-sm">
      <div>
        <p className="break-all font-medium">{inviteLinkForCode(code)}</p>
        <p className="text-muted-foreground text-xs">{t("users.newInviteLinkOnce")}</p>
      </div>
      <Button variant="outline" size="icon" onClick={() => void copy()}>
        <Copy className="h-4 w-4" />
        <span className="sr-only">{t("users.copyInviteLink")}</span>
      </Button>
    </div>
  );
};

/**
 * Live "N uses · expires M" line for one invite. A component (not an inline
 * hook) so `useRelativeTime` can run per invite inside the invites map.
 */
const InviteUsesLine = ({ invite }: { invite: CommunityInviteRead }) => {
  const { t } = useTranslation("communities");
  const relativeExpiry = useRelativeTime(invite.expires_at);
  const expires = invite.expires_at != null ? relativeExpiry : t("users.neverExpires");
  return (
    <p className="text-muted-foreground">
      {t("users.usesFormat", { uses: invite.uses, max: invite.max_uses ?? "∞", expires })}
    </p>
  );
};

/** A community's invites, each with how it has been used and a delete button. */
export const CommunityInviteList = ({
  invites,
  isLoading,
  error,
  emptyText,
  onDelete,
  detail,
}: {
  invites: CommunityInviteRead[];
  isLoading: boolean;
  error: string | null;
  emptyText: string;
  onDelete: (inviteId: number) => void;
  /** More about one invite, under its uses. */
  detail?: (invite: CommunityInviteRead) => ReactNode;
}) => {
  const { t } = useTranslation("communities");
  return (
    <>
      {isLoading ? (
        <SkeletonRegion label={t("users.loadingInvites")}>
          <ListSkeleton rows={2} avatar={false} />
        </SkeletonRegion>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      {!isLoading && !invites.length ? (
        <p className="text-muted-foreground text-sm">{emptyText}</p>
      ) : null}
      <div className="space-y-3">
        {invites.map((invite) => (
          <div
            key={invite.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded border bg-muted/30 p-4 text-sm"
          >
            <div>
              <p className="font-medium">{invite.invitee_email ?? t("users.inviteLinkTitle")}</p>
              <InviteUsesLine invite={invite} />
              {detail?.(invite)}
            </div>
            <Button variant="outline" size="icon" onClick={() => onDelete(invite.id)}>
              <Trash2 className="h-4 w-4" />
              <span className="sr-only">{t("users.deleteInviteLink")}</span>
            </Button>
          </div>
        ))}
      </div>
    </>
  );
};

/**
 * Inviting members to the active community: the form that makes a link, what
 * stops it at the seat cap, the link just made, and the live ones. Settings ›
 * Users shows it, and so does the invite dialog the community's banner and
 * members page open.
 */
export const MemberInvites = ({ invites }: { invites: ReturnType<typeof useCommunityInvites> }) => {
  const { t } = useTranslation("communities");
  const { activeCommunity } = useCommunities();
  const { canSell, openPortal } = useBillingPortal();
  const [limits, setLimits] = useState<InviteLinkLimits>({ maxUses: 1, expiresDays: 7 });

  // Seat cap, admin-only on the payload and null when uncapped. A full community
  // mints no invite (the server refuses), so the form says so up front instead
  // of failing on submit. Where a billing portal exists the cap travels with
  // the plan — raising it is an upgrade, not a request to an operator — so the
  // message and its action differ from the self-hosted one.
  const communityId = activeCommunity?.id ?? null;
  const maxUsers = activeCommunity?.max_users ?? null;
  const atUserLimit = maxUsers !== null && (activeCommunity?.member_count ?? 0) >= maxUsers;
  const planName = activeCommunity?.tier_name ?? null;

  const create = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!atUserLimit) void invites.create(limits);
  };

  return (
    <div className="space-y-4">
      <form className="grid grid-cols-fill-48/3 gap-4" onSubmit={create}>
        <InviteLimitFields idPrefix="invite" value={limits} onChange={setLimits} />
        <div className="flex items-end">
          <Button type="submit" disabled={invites.submitting || atUserLimit}>
            {invites.submitting ? t("users.generatingInvite") : t("users.generateInvite")}
          </Button>
        </div>
      </form>
      {atUserLimit && canSell && communityId && activeCommunity?.can.seat ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground text-sm">
            {planName
              ? t("users.inviteSeatsFullPlan", { plan: planName, count: maxUsers ?? 0 })
              : t("users.inviteSeatsFullUpgrade", { count: maxUsers ?? 0 })}
          </p>
          <Button size="sm" onClick={() => void openPortal(communityId, "upgrade")}>
            {t("usagePanel.upgrade")}
          </Button>
        </div>
      ) : atUserLimit ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-muted-foreground text-sm">
            {t("users.inviteSeatsFull", { max: maxUsers })}
          </p>
          <HelpLink topic={SupportTopic.community} communityId={communityId} />
        </div>
      ) : null}
      {invites.newInviteCode ? <NewInviteLink code={invites.newInviteCode} /> : null}
      <div className="h-px bg-border" />
      {/* Guest invites are Settings › Guests'; these are for members. */}
      <CommunityInviteList
        invites={invites.invites.filter((invite) => invite.guest_days == null)}
        isLoading={invites.isLoading}
        error={invites.error}
        emptyText={t("users.noActiveInvites")}
        onDelete={(inviteId) => void invites.remove(inviteId)}
      />
    </div>
  );
};

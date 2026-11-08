import { Blocks, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  OwnedContentResponse,
  OwnershipTransferRequest,
  OwnershipTransferResponse,
  Tool,
  UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";
import {
  claimUnownedContent,
  listOwnedContent,
  listUnownedContent,
  transferOwnership,
} from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import type { MemberLike } from "@/components/members/MemberSearchSelect";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { USER_ID_LOOKUP_MAX, useUserSearch } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { isAdminRole } from "@/lib/permissions";
import { toolCamelPlural } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Combobox, type ComboboxItem } from "@/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";

/**
 * Counts keyed by tool, rendered as "3 projects · 1 calendar". The label comes
 * from the tool's own nav string, so a new tool needs nothing here.
 */
const useToolCounts = (counts: Record<string, number> | undefined) => {
  const { t } = useTranslation(["nav"]);
  return useMemo(
    () =>
      Object.entries(counts ?? {}).map(([tool, count]) => ({
        tool,
        count,
        label: t(`nav:${toolCamelPlural(tool as Tool)}` as never),
      })),
    [counts, t]
  );
};

/** A recipient in the picker: an admin (`user:<id>`) or a plug-in (`plugin:<id>`). */
const personRecipient = (id: number) => `user:${id}`;
const pluginRecipient = (id: number) => `plugin:${id}`;

/** The request body a picked recipient becomes. */
const transferBody = (recipient: string): OwnershipTransferRequest => {
  const [kind, id] = recipient.split(":");
  return kind === "plugin" ? { new_owner_plugin_id: Number(id) } : { new_owner_id: Number(id) };
};

interface TransferContentOwnershipDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whose content moves. Null claims everything nobody owns instead. */
  member: UserCommunityMember | null;
  /** Pre-selected recipient — the acting admin. */
  defaultRecipient?: MemberLike | null;
  onSuccess?: () => void;
}

/**
 * Moves everything a member owns in this community to a community admin, and the only
 * place in the plug-in that does. Recipients are community admins, who already reach
 * every part of the community, so a transfer can never widen anyone's access — or
 * an installed plug-in the server lists as able to own all of it
 * (`eligible_plugins`): one placed where all of it lives and allowed to change
 * it, which is the reach it already has.
 *
 * With `member` null it claims the community's unowned content instead — the pile
 * that accumulates as people leave, since departures release ownership rather
 * than handing it on.
 */
export const TransferContentOwnershipDialog = ({
  open,
  onOpenChange,
  member,
  defaultRecipient: defaultRecipientUser,
  onSuccess,
}: TransferContentOwnershipDialogProps) => {
  const { t } = useTranslation(["communities", "common"]);
  const communityId = useActiveCommunityId();
  const defaultRecipient = defaultRecipientUser ? personRecipient(defaultRecipientUser.id) : "";
  const [recipientId, setRecipientId] = useState<string>(defaultRecipient);
  // The picked recipient's name, held because the search that offered it moves on.
  const [recipientLabel, setRecipientLabel] = useState<string | null>(null);
  const [content, setContent] = useState<OwnedContentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const isClaim = member === null;

  const memberId = member?.id ?? null;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setContent(null);
    setLoading(true);
    setRecipientId(defaultRecipient);
    setRecipientLabel(null);

    const load = async () => {
      try {
        const data = (memberId === null
          ? await listUnownedContent(communityId)
          : await listOwnedContent(communityId, memberId)) as unknown as OwnedContentResponse;
        if (!cancelled) setContent(data);
      } catch (err) {
        console.error("Failed to load owned content", err);
        if (!cancelled)
          toast.error(getErrorMessage(err, "communities:transferOwnership.loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, memberId, communityId, defaultRecipient]);

  const toolCounts = useToolCounts(content?.counts);
  const nothingToMove = !loading && (content?.total ?? 0) === 0;
  const eligiblePlugins = content?.eligible_plugins ?? [];

  // Admins are found by name on the server rather than read from the whole
  // roster: the closest matches, of which the admins are offered. The few plug-ins
  // the server listed are matched here.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const adminSearch = useUserSearch({
    search,
    pageSize: USER_ID_LOOKUP_MAX,
    enabled: open && pickerOpen,
  });
  const recipients = useMemo<ComboboxItem[]>(() => {
    const term = search.trim().toLowerCase();
    return [
      ...(adminSearch.data?.items ?? [])
        .filter((user) => isAdminRole(user.community_role) && user.status !== "anonymized")
        .map((admin) => ({ value: personRecipient(admin.id), label: getUserDisplayName(admin) })),
      ...(content?.eligible_plugins ?? [])
        .filter((plugin) => plugin.name.toLowerCase().includes(term))
        .map((plugin) => ({
          value: pluginRecipient(plugin.id),
          label: plugin.name,
          icon: Blocks,
          hint: t("transferOwnership.pluginHint"),
        })),
    ];
  }, [adminSearch.data, content, search, t]);
  const selectedLabel =
    recipientLabel ??
    (recipientId && recipientId === defaultRecipient && defaultRecipientUser
      ? getUserDisplayName(defaultRecipientUser)
      : null);

  const handleSubmit = async () => {
    if (!recipientId) return;
    setSubmitting(true);
    try {
      const body = transferBody(recipientId);
      const result = (member === null
        ? await claimUnownedContent(communityId, body)
        : await transferOwnership(
            communityId,
            member.id,
            body
          )) as unknown as OwnershipTransferResponse;
      void invalidate(q.communityMembers());
      toast.success(t("transferOwnership.moved", { count: result.total }));
      onSuccess?.();
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to transfer ownership", err);
      toast.error(getErrorMessage(err, "communities:transferOwnership.failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isClaim ? t("transferOwnership.claimTitle") : t("transferOwnership.title")}
          </DialogTitle>
          <DialogDescription>
            {isClaim
              ? t("transferOwnership.claimDescription")
              : t("transferOwnership.description", {
                  name: member ? getUserDisplayName(member) : "",
                })}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : nothingToMove ? (
          <p className="text-muted-foreground text-sm">
            {isClaim ? t("transferOwnership.nothingUnowned") : t("transferOwnership.nothingOwned")}
          </p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2 rounded-md border p-3">
              <p className="font-medium text-sm">{t("transferOwnership.whatMoves")}</p>
              <ul className="space-y-1">
                {toolCounts.map(({ tool, count, label }) => (
                  <li key={tool} className="text-muted-foreground text-sm">
                    {count} × {label}
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-2">
              <Label>{t("transferOwnership.recipientLabel")}</Label>
              <Combobox
                items={recipients}
                value={recipientId}
                onValueChange={(value) => {
                  setRecipientId(value);
                  setRecipientLabel(recipients.find((item) => item.value === value)?.label ?? null);
                }}
                onSearchChange={setSearch}
                onOpenChange={setPickerOpen}
                selectedLabel={selectedLabel}
                loading={adminSearch.isFetching && recipients.length === 0}
                placeholder={t("transferOwnership.recipientPlaceholder")}
                aria-label={t("transferOwnership.recipientLabel")}
              />
              <p className="text-muted-foreground text-xs">
                {eligiblePlugins.length > 0
                  ? t("transferOwnership.adminsOrPlugins")
                  : t("transferOwnership.adminsOnly")}
              </p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("common:cancel")}
          </Button>
          {!nothingToMove && !loading && (
            <Button onClick={handleSubmit} disabled={submitting || !recipientId}>
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("transferOwnership.transferring")}
                </>
              ) : (
                t("transferOwnership.confirm")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * Bring a deleted community back.
 *
 * Deleting a community keeps it — everything stays where it is until the
 * retention window runs out — so restoring is mostly a matter of deciding what
 * it comes back as. Two questions, and only the ones that apply:
 *
 * - **Who runs it.** Asked only when the roster no longer holds the seat that
 *   configures a community, which is what a deletion that cleared the roster
 *   leaves behind (the operator path that unblocks deleting a user). Restoring
 *   one nobody can administer produces a community that is live and
 *   unreachable, so this cannot be skipped.
 * - **What status.** The operator says, rather than the community remembering:
 *   one suspended for nonpayment and then deleted should not come back
 *   trading.
 *
 * What does not come back is its plug-in connections. Those were revoked when it
 * was deleted — the community had withdrawn their authorization — and its
 * admins reconnect them.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformCommunityStorageRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityStatus } from "@/api/generated/initiativeAPI.schemas";
import { usePlatformUsers } from "@/hooks/useOperatorUsers";
import { useRestoreCommunity } from "@/hooks/useSettings";
import { useWizard } from "@/hooks/useWizard";
import { OPERATOR_SETTABLE_STATUSES } from "@/lib/communityStatus";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { getUserHandle } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { Field } from "@/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { WizardDialog } from "@/ui/wizard-dialog";

type Step = "seat" | "status";

export const CommunityRestoreWizard = ({
  community,
  open,
  onOpenChange,
}: {
  community: PlatformCommunityStorageRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  // The seat step is skipped entirely when there is somebody to run it, so the
  // wizard starts wherever the first real question is.
  const needsSeat = !community.has_seat;
  const wizard = useWizard<Step>(needsSeat ? "seat" : "status");
  const [seatUserId, setSeatUserId] = useState<string>("");
  const [seatLabel, setSeatLabel] = useState<string | null>(null);
  const [seatSearch, setSeatSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [status, setStatus] = useState<CommunityStatus>(CommunityStatus.active);

  // Searched on the server, and only while the picker is open: the accounts
  // are every account on the deployment, and most restores never ask.
  const usersQuery = usePlatformUsers(
    { search: seatSearch || undefined, page_size: 25 },
    { enabled: open && needsSeat && pickerOpen }
  );

  const restore = useRestoreCommunity({
    onSuccess: (row) => {
      toast.success(t("communities.restore.done", { name: row.name }));
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:communities.restore.error"));
    },
  });

  const submit = () =>
    restore.mutate({
      communityId: community.id,
      data: {
        status,
        seat_user_id: needsSeat ? Number(seatUserId) : null,
      },
    });

  const userItems = (usersQuery.data?.items ?? []).map((user) => ({
    value: String(user.id),
    label: getUserHandle(user),
    hint: user.email ?? undefined,
  }));

  if (wizard.step === "seat") {
    return (
      <WizardDialog
        open={open}
        onOpenChange={onOpenChange}
        title={t("communities.restore.title", { name: community.name })}
        description={t("communities.restore.seatDescription")}
        progress={{ current: 1, total: 2 }}
      >
        <Field label={t("communities.restore.seatLabel")} hint={t("communities.restore.seatHelp")}>
          <Combobox
            className="w-full"
            value={seatUserId || null}
            selectedLabel={seatLabel}
            onValueChange={(value) => {
              setSeatUserId(value);
              setSeatLabel(userItems.find((item) => item.value === value)?.label ?? null);
            }}
            onSearchChange={setSeatSearch}
            onOpenChange={setPickerOpen}
            items={userItems}
            loading={usersQuery.isFetching}
            placeholder={t("communities.restore.seatPlaceholder")}
            emptyMessage={t("communities.restore.seatEmpty")}
            aria-label={t("communities.restore.seatLabel")}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => wizard.go("status")} disabled={seatUserId === ""}>
            {t("common:next")}
          </Button>
        </div>
      </WizardDialog>
    );
  }

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("communities.restore.title", { name: community.name })}
      description={t("communities.restore.statusDescription")}
      progress={needsSeat ? { current: 2, total: 2 } : undefined}
      onBack={needsSeat ? wizard.back : undefined}
      backLabel={t("common:back")}
      backDisabled={restore.isPending}
    >
      <Field
        label={t("communities.restore.statusLabel")}
        hint={t("communities.restore.pluginsNote")}
      >
        <Select
          value={status}
          onValueChange={(value) => setStatus(value as CommunityStatus)}
          disabled={restore.isPending}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OPERATOR_SETTABLE_STATUSES.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`communities.status.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={restore.isPending}>
          {t("common:cancel")}
        </Button>
        <Button onClick={submit} disabled={restore.isPending}>
          {restore.isPending ? t("common:submitting") : t("communities.restore.confirm")}
        </Button>
      </div>
    </WizardDialog>
  );
};

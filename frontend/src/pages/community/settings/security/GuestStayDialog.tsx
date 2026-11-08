import { useTranslation } from "react-i18next";

import type { CommunityAuthSettingsRead } from "@/api/generated/initiativeAPI.schemas";
import { useUpdateCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { readOptionalWholeNumber } from "@/lib/text";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/**
 * The longest a guest may stay. Blank leaves only the server's limit, which
 * also caps whatever is set here.
 */
export const GuestStayDialog = ({
  communityId,
  authSettings,
  open,
  onOpenChange,
}: {
  communityId: number;
  authSettings: CommunityAuthSettingsRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const ceiling = authSettings.guest_max_days_by_platform;
  const form = useServerForm(
    authSettings,
    (loaded) => ({ days: loaded?.guest_max_days == null ? "" : String(loaded.guest_max_days) }),
    [open, communityId]
  );
  const update = useUpdateCommunityAuthSettings(communityId);
  const { value: days, valid } = readOptionalWholeNumber(form.values.days, 1, ceiling);

  const save = () =>
    update.mutate(
      { guest_max_days: days },
      {
        onSuccess: () => {
          toast.success(t("communityAuth.guestStay.saved"));
          onOpenChange(false);
        },
        onError: (err: unknown) => {
          toast.error(getErrorMessage(err, "settings:communityAuth.guestStay.error"));
        },
      }
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("communityAuth.guestStay.title")}</DialogTitle>
          <DialogDescription>{t("communityAuth.guestStay.description")}</DialogDescription>
        </DialogHeader>
        <Field
          label={t("communityAuth.guestStay.label")}
          hint={t("communityAuth.guestStay.hint", { count: ceiling })}
        >
          <Input
            type="number"
            min={1}
            max={ceiling}
            className="w-40"
            value={form.values.days}
            placeholder={String(ceiling)}
            onChange={(event) => form.set({ days: event.target.value })}
          />
        </Field>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={!valid || days === authSettings.guest_max_days}
          onSubmit={save}
        />
      </DialogContent>
    </Dialog>
  );
};

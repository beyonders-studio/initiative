import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTimeOutMember } from "@/hooks/useUsers";
import { toast } from "@/lib/mascotToast";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Label } from "@/ui/label";
import { formatDateTime, fromLocalDateTimeInput } from "@/ui/lib/formatDate";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const HOUR_MS = 60 * 60 * 1000;
/** The lengths offered first, in milliseconds; anything else is picked as a date. */
const LENGTHS = { hour: HOUR_MS, day: 24 * HOUR_MS, week: 7 * 24 * HOUR_MS } as const;
type Length = keyof typeof LENGTHS | "custom";

interface TimeOutMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  member: { id: number; name: string } | null;
}

/**
 * Time a member out: for a while they read the community and change nothing in
 * it, the way everybody does in a read-only one. It ends by itself; setting
 * another replaces it.
 */
export const TimeOutMemberDialog = ({ open, onOpenChange, member }: TimeOutMemberDialogProps) => {
  const { t } = useTranslation("communities");
  const lengthId = useId();
  const untilId = useId();
  const [length, setLength] = useState<Length>("hour");
  const [until, setUntil] = useState("");
  const close = () => {
    setLength("hour");
    setUntil("");
    onOpenChange(false);
  };
  const timeOut = useTimeOutMember({
    onSuccess: (_data, { endsAt }) => {
      toast.success(t("timeOut.done", { name: member?.name, time: formatDateTime(endsAt) }));
      close();
    },
  });

  const endsAt = (): Date | null => {
    if (length !== "custom") return new Date(Date.now() + LENGTHS[length]);
    const chosen = fromLocalDateTimeInput(until);
    return chosen ? new Date(chosen) : null;
  };

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={t("timeOut.title", { name: member?.name })}
      description={t("timeOut.description")}
      confirmLabel={t("timeOut.confirm")}
      loadingLabel={t("timeOut.confirming")}
      isLoading={timeOut.isPending}
      confirmDisabled={length === "custom" && !fromLocalDateTimeInput(until)}
      onConfirm={() => {
        const end = endsAt();
        if (member && end) timeOut.mutate({ userId: member.id, endsAt: end });
      }}
    >
      <div className="space-y-2">
        <Label htmlFor={lengthId}>{t("timeOut.lengthLabel")}</Label>
        <Select value={length} onValueChange={(value) => setLength(value as Length)}>
          <SelectTrigger id={lengthId}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(["hour", "day", "week", "custom"] as const).map((option) => (
              <SelectItem key={option} value={option}>
                {t(`timeOut.length.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {length === "custom" ? (
        <div className="space-y-2">
          <Label htmlFor={untilId}>{t("timeOut.untilLabel")}</Label>
          <DateTimePicker id={untilId} value={until} onChange={setUntil} includeTime />
        </div>
      ) : null}
    </ConfirmDialog>
  );
};

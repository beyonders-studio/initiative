import { useTranslation } from "react-i18next";

import { PASSWORD_MIN_LENGTH } from "@/lib/passwordPolicy";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

/**
 * A new password and its confirmation, with the length the policy asks for
 * under the first, turning red while what is typed falls short of it.
 * `checkNewPassword` is the check the form runs on submit.
 *
 * Renders the two fields side by side as siblings, so the caller lays them
 * out (stacked in a sign-in card, a grid in settings).
 */
export const NewPasswordFields = ({
  id,
  label,
  password,
  confirm,
  onPasswordChange,
  onConfirmChange,
}: {
  /** The first field's id; the confirmation's is `${id}-confirm`. */
  id: string;
  label: string;
  password: string;
  confirm: string;
  onPasswordChange: (password: string) => void;
  onConfirmChange: (confirm: string) => void;
}) => {
  const { t } = useTranslation("auth");
  const short = password.length > 0 && password.length < PASSWORD_MIN_LENGTH;
  return (
    <>
      <div className="space-y-2">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="password"
          value={password}
          onChange={(event) => onPasswordChange(event.target.value)}
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          aria-describedby={`${id}-hint`}
          required
        />
        <p
          id={`${id}-hint`}
          className={short ? "text-destructive text-xs" : "text-muted-foreground text-xs"}
        >
          {t("passwordPolicy.minLengthHelp")}
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${id}-confirm`}>{t("passwordPolicy.confirmLabel")}</Label>
        <Input
          id={`${id}-confirm`}
          type="password"
          value={confirm}
          onChange={(event) => onConfirmChange(event.target.value)}
          autoComplete="new-password"
          required
        />
      </div>
    </>
  );
};

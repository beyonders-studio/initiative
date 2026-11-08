import { useTranslation } from "react-i18next";

import { PASSWORD_MIN_LENGTH } from "@/lib/passwordPolicy";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

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
  const help = t("passwordPolicy.minLengthHelp");
  return (
    <>
      <Field label={label} hint={!short && help} error={short && help} id={id}>
        <Input
          type="password"
          value={password}
          onChange={(event) => onPasswordChange(event.target.value)}
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          required
        />
      </Field>
      <Field label={t("passwordPolicy.confirmLabel")} id={`${id}-confirm`}>
        <Input
          type="password"
          value={confirm}
          onChange={(event) => onConfirmChange(event.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
    </>
  );
};

import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/** The invite code or link, and what checking it found. */
export const InviteStep = ({
  code,
  onCodeChange,
  status,
  error,
  checking,
  canContinue,
  onSubmit,
}: {
  code: string;
  onCodeChange: (code: string) => void;
  /** Where the invite leads, once checked. */
  status: string | null;
  error: string | null;
  checking: boolean;
  canContinue: boolean;
  onSubmit: () => void;
}) => {
  const { t } = useTranslation("auth");
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Field label={t("start.invite.codeLabel")}>
        <Input
          value={code}
          onChange={(event) => onCodeChange(event.target.value)}
          autoCapitalize="none"
          autoComplete="off"
        />
      </Field>
      {status ? <p className="text-muted-foreground text-sm">{status}</p> : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <Button type="submit" className="w-full" disabled={checking || !canContinue}>
        {t("start.continue")}
      </Button>
    </form>
  );
};

import { useTranslation } from "react-i18next";

import { PrivacyLink } from "@/components/auth/LegalNotice";
import { useAppConfig } from "@/hooks/useAppConfig";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Label } from "@/ui/label";

/**
 * The question, with a note under it that the answer is not shared and, where
 * the deployment publishes one, a link to its privacy policy. The note sits
 * with the field rather than in each caller so every surface that asks says
 * the same thing.
 *
 * The date is picked with the same control as every other date in the app —
 * type it or reach it through the year dropdown — rather than the browser's
 * own, which differs on every platform and, on a birthday, means paging back
 * decades a month at a time.
 */
export const BirthdateField = ({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation(["auth", "legal"]);
  // A deployment with legal documents of its own has a privacy policy to link.
  const { billing } = useAppConfig();
  // The window the server will accept: born by today, and no more than a
  // lifetime ago. Matched here so nothing the calendar offers is a date the
  // server then refuses — including the day at each edge, which is why the
  // bounds are built from today's *UTC* date, the one the server compares
  // against. A reader far enough east or west has a different local date, and
  // taking theirs would offer an edge day the server does not accept.
  const now = new Date();
  const today = new Date(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const earliest = new Date(now.getUTCFullYear() - 120, now.getUTCMonth(), now.getUTCDate());
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("auth:confirmAge.birthdateLabel")}</Label>
      <DateTimePicker
        id={id}
        value={value}
        onChange={onChange}
        disabled={disabled}
        includeTime={false}
        placeholder={t("auth:confirmAge.birthdatePlaceholder")}
        calendarProps={{
          // A lifetime of years to choose from, and nothing outside the window:
          // nobody was born tomorrow, or before the oldest person alive.
          startMonth: earliest,
          endMonth: today,
          hidden: { before: earliest, after: today },
        }}
      />
      <p className="text-muted-foreground text-xs">
        {t("auth:confirmAge.privacyNote")}
        {billing ? (
          <>
            {" "}
            <PrivacyLink />
          </>
        ) : null}
      </p>
    </div>
  );
};

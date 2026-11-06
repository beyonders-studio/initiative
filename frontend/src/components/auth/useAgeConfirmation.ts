import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmMyAge } from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";

/**
 * Answering the age question, wherever it is asked.
 *
 * Two surfaces ask it — the screen an account meets when it already belongs
 * somewhere open, and the dialog the directory's Join button opens — and they
 * differ only in the chrome around them. The date, what is done with it and
 * what comes back when it is refused live here, so the two cannot drift into
 * disagreeing about any of it.
 *
 * The date is sent and not kept: the server compares it, answers, and writes
 * down only that the question was answered. Nothing here holds it after the
 * request, and the field is cleared on the way out.
 */
export const useAgeConfirmation = (onConfirmed?: () => void) => {
  const { t } = useTranslation(["auth"]);
  const { refreshUser } = useAuth();
  const [birthdate, setBirthdate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (!birthdate) {
      setError(t("auth:confirmAge.required"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await confirmMyAge({ birthdate });
      await refreshUser();
      // The answer is a gate rather than a preference: who may reach this
      // account, who it may reach, and whether it has a messaging policy at
      // all are all different now. Anything holding the old answer is dropped,
      // so the surface that asked shows what the answer opened instead of
      // needing a reload to notice.
      await invalidate(q.dmSettings(), q.people(), q.contactGrants());
      setBirthdate("");
      onConfirmed?.();
    } catch (err) {
      // An answer under the minimum is recorded before it is refused.
      if (getErrorCode(err) === "USER_AGE_BELOW_MINIMUM") await refreshUser();
      setError(getErrorMessage(err, "auth:confirmAge.error"));
    } finally {
      setSubmitting(false);
    }
  };

  /** Forget the date and anything said about it.
   *
   *  A surface that can be dismissed calls this on the way out. Backing out of
   *  the question is not answering it, and holding the date afterwards would
   *  contradict the note printed under the field — as well as handing the next
   *  person to open the dialog a date somebody else chose not to submit. */
  const reset = () => {
    setBirthdate("");
    setError(null);
  };

  return { birthdate, setBirthdate, submitting, error, confirm, reset };
};

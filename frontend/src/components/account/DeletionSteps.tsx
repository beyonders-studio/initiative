import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "@/ui/alert";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

interface EligibilityStepProps {
  checking: boolean;
  /** The check's verdict; undefined until it has answered. */
  canDelete: boolean | undefined;
  /** One translated line per thing in the way. */
  blockers: string[];
  blockedTitle: string;
  blockedHint: string;
  eligibleText: string;
}

/** The account deletion dialogs' eligibility step: a spinner while the check
 *  runs, then what stands in the way or that nothing does. */
export function EligibilityStep({
  checking,
  canDelete,
  blockers,
  blockedTitle,
  blockedHint,
  eligibleText,
}: EligibilityStepProps) {
  if (checking) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (canDelete === false) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          <div className="mb-2 font-semibold">{blockedTitle}</div>
          <ul className="list-inside list-disc space-y-1">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
          <p className="mt-2 text-sm">{blockedHint}</p>
        </AlertDescription>
      </Alert>
    );
  }
  if (canDelete) {
    return (
      <Alert className="border-green-500/50 bg-green-50 dark:bg-green-950">
        <AlertDescription>{eligibleText}</AlertDescription>
      </Alert>
    );
  }
  return null;
}

interface ConfirmPhraseFieldProps {
  phrase: string;
  value: string;
  onChange: (value: string) => void;
}

/** The phrase a deletion dialog asks to be typed back before it acts. */
export function ConfirmPhraseField({ phrase, value, onChange }: ConfirmPhraseFieldProps) {
  const { t } = useTranslation("settings");
  return (
    <Field
      label={
        <>
          {t("accountDeletion.typeToConfirmPrefix")}{" "}
          <span className="font-bold font-mono">{phrase}</span>{" "}
          {t("accountDeletion.typeToConfirmSuffix")}
        </>
      }
    >
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={phrase} />
    </Field>
  );
}

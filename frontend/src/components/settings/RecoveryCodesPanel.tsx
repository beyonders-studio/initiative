import { useTranslation } from "react-i18next";

import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { DialogFooter } from "@/ui/dialog";

interface RecoveryCodesPanelProps {
  /** The set, readable here and nowhere else. */
  codes: string[];
  /** What they are for, in the words of the place showing them. */
  note: string;
  /** Closing the dialog they are shown in. */
  onDone: () => void;
}

/**
 * A set of recovery codes, the once.
 *
 * Shown after an enrolment, after a re-issue, and after a password is given
 * up. Each of those shows the same list, the same copy button and the same
 * Done; the line above the codes is the only part that differs, which is what
 * `note` is.
 */
export const RecoveryCodesPanel = ({ codes, note, onDone }: RecoveryCodesPanelProps) => {
  const { t } = useTranslation("settings");

  const copy = () => {
    // These are shown once. A copy that quietly did not happen would leave
    // somebody thinking they had them.
    if (!navigator?.clipboard) {
      toast.error(t("twoFactor.copyUnavailable"));
      return;
    }
    void navigator.clipboard
      .writeText(codes.join("\n"))
      .then(() => toast.success(t("twoFactor.codesCopied")))
      .catch(() => toast.error(t("twoFactor.copyUnavailable")));
  };

  return (
    <div className="space-y-4">
      <ul className="grid grid-cols-2 gap-1 rounded bg-muted p-3 font-mono text-sm">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <p className="text-muted-foreground text-sm">{note}</p>
      <DialogFooter className="gap-2">
        <Button variant="outline" onClick={copy} type="button">
          {t("twoFactor.copyCodes")}
        </Button>
        <Button onClick={onDone} type="button">
          {t("twoFactor.done")}
        </Button>
      </DialogFooter>
    </div>
  );
};

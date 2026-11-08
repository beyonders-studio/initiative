import { AlertCircle, ChevronLeft } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { ConfirmPhraseField, EligibilityStep } from "@/components/account/DeletionSteps";
import { useMyDeletionEligibility } from "@/hooks/useOperatorUsers";
import { useDeleteOwnAccount } from "@/hooks/useUsers";
import { useWizard } from "@/hooks/useWizard";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { DialogWithSuccessProps } from "@/types/dialog";
import { Alert, AlertDescription } from "@/ui/alert";
import { Button } from "@/ui/button";
import { DialogFooter } from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { WizardDialog } from "@/ui/wizard-dialog";

/**
 * Self-deletion is constrained to two actions:
 *   - ``deactivate`` — reversible, PII intact, an operator can reactivate later.
 *   - ``soft_delete`` — anonymize (PII removed), permanent.
 * Hard delete is operator-only and lives on the operator endpoint; the
 * self-service endpoint rejects ``hard_delete`` with 403.
 */
type SelfAction = "deactivate" | "soft_delete";
type DeletionStep = "choose-type" | "check-blockers" | "confirm";

interface DeleteAccountDialogProps extends DialogWithSuccessProps {
  user: UserRead;
  /** When provided, the dialog skips the choose-type step and starts
   *  directly on the eligibility check for that action. This lets the
   *  Danger Zone page surface "Deactivate" and "Delete" as separate
   *  buttons instead of a single ambiguous opener. */
  initialAction?: SelfAction;
}

const CONFIRMATION_PHRASES: Record<SelfAction, string> = {
  deactivate: "DEACTIVATE MY ACCOUNT",
  soft_delete: "DELETE MY ACCOUNT",
};

export function DeleteAccountDialog({
  open,
  onOpenChange,
  onSuccess,
  user,
  initialAction,
}: DeleteAccountDialogProps) {
  const { t } = useTranslation(["settings", "errors"]);
  const initialStep: DeletionStep = initialAction ? "check-blockers" : "choose-type";
  const { step, go, back, canGoBack, reset } = useWizard<DeletionStep>(initialStep);
  const [action, setAction] = useState<SelfAction>(initialAction ?? "deactivate");
  const [password, setPassword] = useState("");
  const [confirmationText, setConfirmationText] = useState("");

  // Sync internal state to ``open`` / ``initialAction``. The dialog
  // stays mounted across openings (the parent only flips ``open``), so
  // ``useState`` initial values run once and would never honor a new
  // ``initialAction`` on a subsequent open. We reset on every
  // transition so:
  //   - On open: ``step`` and ``action`` reflect this open's
  //     ``initialAction``. Without this, clicking "Delete Account"
  //     would still show ``action === "deactivate"`` from the initial
  //     mount.
  //   - On close: per-attempt fields (the eligibility answer, password,
  //     confirmation text) are cleared so the next open is a clean slate.
  useEffect(() => {
    reset();
    setAction(initialAction ?? "deactivate");
    if (!open) {
      setPassword("");
      setConfirmationText("");
    }
  }, [open, initialAction, reset]);

  const {
    data: eligibility,
    refetch: checkEligibility,
    isFetching: isCheckingEligibility,
  } = useMyDeletionEligibility(open);

  const deleteAccount = useDeleteOwnAccount({
    onSuccess: () => {
      toast.success(
        action === "deactivate"
          ? t("deleteAccount.deactivateSuccess")
          : t("deleteAccount.softDeleteSuccess")
      );
      onSuccess();
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:deleteAccount.deleteError"));
    },
  });

  // Run the eligibility check and advance past ``check-blockers`` when
  // the user is eligible. Shared between the explicit "Next" press
  // from the chooser step and the auto-fire on dialog open when
  // ``initialAction`` skipped the chooser.
  const runEligibilityCheck = useCallback(async () => {
    const result = await checkEligibility();
    if (result.data?.can_delete) {
      go("confirm");
    }
  }, [checkEligibility, go]);

  // When opened with ``initialAction``, the chooser step is bypassed
  // and we land directly on ``check-blockers`` — kick off the check.
  // Guard with a ref so a re-render doesn't refetch.
  const eligibilityFiredRef = useRef(false);
  useEffect(() => {
    if (!open) {
      eligibilityFiredRef.current = false;
      return;
    }
    if (!initialAction || eligibilityFiredRef.current) return;
    eligibilityFiredRef.current = true;
    void runEligibilityCheck();
  }, [open, initialAction, runEligibilityCheck]);

  // Step navigation handlers
  const handleNext = async () => {
    if (step === "choose-type") {
      go("check-blockers");
      await runEligibilityCheck();
    } else if (step === "check-blockers") {
      if (eligibility?.can_delete) {
        go("confirm");
      }
    }
  };

  const handleSubmit = () => {
    deleteAccount.mutate({
      action,
      password,
      confirmation_text: confirmationText,
    });
  };

  const expectedConfirmation = CONFIRMATION_PHRASES[action];
  // Some accounts are not asked for a password — they hold none, or the
  // deployment signs nobody in with one. The server asks for a recent sign-in
  // instead, so the dialog offers no field to fill.
  const passwordless = !user.password_required;

  // Validation
  const canProceedFromChooseType = action !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
  const canConfirm =
    (passwordless || password.length > 0) && confirmationText === expectedConfirmation;

  const description: Record<DeletionStep, string> = {
    "choose-type": t("deleteAccount.chooseTypeDescription"),
    "check-blockers": t(
      action === "deactivate"
        ? "deleteAccount.checkBlockersDeactivateDescription"
        : "deleteAccount.checkBlockersDescription"
    ),
    confirm: t(
      action === "deactivate"
        ? "deleteAccount.confirmDeactivationDescription"
        : "deleteAccount.confirmDeletionDescription"
    ),
  };
  const walked: DeletionStep[] = initialAction
    ? ["check-blockers", "confirm"]
    : ["choose-type", "check-blockers", "confirm"];

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
      // When the dialog was opened with a specific action (the Danger Zone's
      // per-action buttons), reflect that in the title — the user already
      // chose, no point still calling it "Delete Account" while they're
      // deactivating.
      title={
        initialAction === "deactivate"
          ? t("deleteAccount.deactivateTitle")
          : t("deleteAccount.title")
      }
      description={description[step]}
      // Opened from a per-action button, the chooser never happens, so there
      // are two questions rather than three.
      progress={{ current: walked.indexOf(step) + 1, total: walked.length }}
    >
      <div className="space-y-6 py-4">
        {/* Step 1: Choose action */}
        {step === "choose-type" && (
          <RadioGroup value={action} onValueChange={(value) => setAction(value as SelfAction)}>
            <div className="space-y-4">
              <div className="flex items-start space-x-3 rounded-lg border p-4">
                <RadioGroupItem value="deactivate" id="deactivate" className="mt-0.5" />
                <div className="flex-1 space-y-1">
                  <Label htmlFor="deactivate" className="cursor-pointer font-medium text-base">
                    {t("deleteAccount.deactivateLabel")}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t("deleteAccount.deactivateRadioDescription")}
                  </p>
                </div>
              </div>

              <div className="flex items-start space-x-3 rounded-lg border border-destructive/50 p-4">
                <RadioGroupItem value="soft_delete" id="soft_delete" className="mt-0.5" />
                <div className="flex-1 space-y-1">
                  <Label
                    htmlFor="soft_delete"
                    className="cursor-pointer font-medium text-base text-destructive"
                  >
                    {t("deleteAccount.softDeleteLabel")}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t("deleteAccount.softDeleteRadioDescription")}
                  </p>
                </div>
              </div>
            </div>
          </RadioGroup>
        )}

        {/* Step 2: Check Blockers */}
        {step === "check-blockers" && (
          <EligibilityStep
            checking={isCheckingEligibility}
            canDelete={eligibility?.can_delete}
            blockers={[
              ...(eligibility?.last_owner ? [t("errors:USER_CANNOT_REMOVE_LAST_OWNER")] : []),
              ...(eligibility?.sole_superadmin_communities ?? []).map((communityName) =>
                t("deleteAccount.soleSuperadminBlocker", { communityName })
              ),
            ]}
            blockedTitle={t(
              action === "deactivate"
                ? "deleteAccount.cannotDeactivate"
                : "deleteAccount.cannotDelete"
            )}
            blockedHint={t(
              action === "deactivate"
                ? "deleteAccount.resolveIssuesDeactivate"
                : "deleteAccount.resolveIssues"
            )}
            eligibleText={t(
              action === "deactivate"
                ? "deleteAccount.eligibleDeactivate"
                : "deleteAccount.eligible"
            )}
          />
        )}

        {/* Step 3: Confirm */}
        {step === "confirm" && (
          <div className="space-y-4">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <div className="mb-2 font-semibold">{t("deleteAccount.actionSerious")}</div>
                <p className="text-sm">
                  {t(
                    action === "deactivate"
                      ? "deleteAccount.deactivateConfirmDescription"
                      : "deleteAccount.softDeleteConfirmDescription"
                  )}
                </p>
              </AlertDescription>
            </Alert>

            {!passwordless && (
              <Field label={t("deleteAccount.confirmPasswordLabel")} id="password">
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("deleteAccount.enterPassword")}
                />
              </Field>
            )}

            <ConfirmPhraseField
              phrase={expectedConfirmation}
              value={confirmationText}
              onChange={setConfirmationText}
            />
          </div>
        )}
      </div>

      <DialogFooter>
        <div className="flex w-full justify-between">
          <Button variant="outline" onClick={back} disabled={!canGoBack || deleteAccount.isPending}>
            <ChevronLeft className="h-4 w-4" />
            {t("deleteAccount.back")}
          </Button>

          <div className="flex gap-2">
            <Button
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={deleteAccount.isPending}
            >
              {t("deleteAccount.cancel")}
            </Button>

            {step !== "confirm" ? (
              <Button
                onClick={handleNext}
                disabled={
                  (step === "choose-type" && !canProceedFromChooseType) ||
                  (step === "check-blockers" && !canProceedFromBlockers)
                }
                pending={isCheckingEligibility}
              >
                {isCheckingEligibility ? t("deleteAccount.checking") : t("deleteAccount.next")}
              </Button>
            ) : (
              <Button
                variant="destructive"
                onClick={handleSubmit}
                disabled={!canConfirm}
                pending={deleteAccount.isPending}
              >
                {deleteAccount.isPending
                  ? t("deleteAccount.deleting")
                  : action === "deactivate"
                    ? t("deleteAccount.deactivateAccount")
                    : t("deleteAccount.deleteAccountButton")}
              </Button>
            )}
          </div>
        </div>
      </DialogFooter>
    </WizardDialog>
  );
}

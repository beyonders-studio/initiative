import { AlertCircle, ChevronLeft, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OperatorUserRead } from "@/api/generated/initiativeAPI.schemas";
import { ConfirmPhraseField, EligibilityStep } from "@/components/account/DeletionSteps";
import { useOperatorDeleteUser, useUserDeletionEligibility } from "@/hooks/useOperatorUsers";
import { useWizard } from "@/hooks/useWizard";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { DialogWithSuccessProps } from "@/types/dialog";
import { Alert, AlertDescription } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { DialogFooter } from "@/ui/dialog";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { WizardDialog } from "@/ui/wizard-dialog";

/**
 * Three actions are exposed in the operator dialog:
 *   - ``deactivate`` — reversible; flips status, drops memberships, PII intact.
 *   - ``soft_delete`` — delete with the deployment's recovery window. The
 *     account keeps everything, is gone for everybody else, and is erased when
 *     the window ends unless its holder signs in or somebody restores it.
 *   - ``hard_delete`` — purge the row, cascade clean up related data.
 * Project transfer is required for all three: only owners hold certain
 * permissions, and a deactivated/anonymized/deleted owner can't act on
 * the projects they own. Transfer is enforced before the action runs so
 * projects always have a usable owner.
 *
 * Hard deletion is the only one with nothing behind it, so its confirm step
 * is a consent screen — and that screen offers the windowed deletion instead,
 * one checkbox away. The dangerous action stays available and stops being the
 * easy mis-click.
 */
type OperatorAction = "deactivate" | "soft_delete" | "hard_delete";
type DeletionStep = "choose-type" | "check-blockers" | "resolve-blockers" | "confirm";

/**
 * Which actions make sense for a target in a given lifecycle state:
 *   - active     → all three (deactivate / anonymize / hard delete)
 *   - deactivated → only anonymize / hard delete (already locked, can't re-deactivate)
 *   - anonymized → only hard delete (PII already gone; deactivate / soft_delete
 *                  are explicitly rejected by the backend with ALREADY_ANONYMIZED)
 * Default selection is the first entry of the list.
 */
const ACTIONS_BY_STATUS: Record<string, readonly OperatorAction[]> = {
  active: ["deactivate", "soft_delete", "hard_delete"],
  deactivated: ["soft_delete", "hard_delete"],
  anonymized: ["hard_delete"],
  // Already deleted and waiting out its window. Deleting it again says
  // nothing; hard deletion is the only thing left that changes anything, and
  // restoring it is a control on the row rather than an action in here.
  deleted: ["hard_delete"],
};
const validActionsFor = (status: string | undefined): readonly OperatorAction[] =>
  ACTIONS_BY_STATUS[status ?? "active"] ?? ACTIONS_BY_STATUS.active;

/** Per-action labels and styling, indexed by OperatorAction. Pulled out of
 *  the JSX so the radio-group render is a simple map over validActions.
 *  ``as const`` preserves the literal type of the translation keys, which
 *  i18next-typed needs to validate them against the Resources union. */
const ACTION_META = {
  deactivate: {
    titleKey: "operatorDeleteUser.deactivateTitle",
    descriptionKey: "operatorDeleteUser.deactivateDescription",
    borderClass: "",
    labelClass: "",
  },
  soft_delete: {
    titleKey: "operatorDeleteUser.softDeleteTitle",
    descriptionKey: "operatorDeleteUser.softDeleteDescription",
    borderClass: "",
    labelClass: "",
  },
  hard_delete: {
    titleKey: "operatorDeleteUser.hardDeleteTitle",
    descriptionKey: "operatorDeleteUser.hardDeleteDescription",
    borderClass: "border-destructive/50",
    labelClass: "text-destructive",
  },
} as const satisfies Record<OperatorAction, unknown>;

interface OperatorDeleteUserDialogProps extends DialogWithSuccessProps {
  targetUser: OperatorUserRead;
  /** The operations case the deletion is for, which hears of it. */
  caseTaskId?: number | null;
}

export function OperatorDeleteUserDialog({
  open,
  onOpenChange,
  onSuccess,
  targetUser,
  caseTaskId,
}: OperatorDeleteUserDialogProps) {
  const { t } = useTranslation(["settings", "errors"]);
  const validActions = validActionsFor(targetUser.status);
  const { step, go, back, canGoBack, reset } = useWizard<DeletionStep>("choose-type");
  const [action, setAction] = useState<OperatorAction>(validActions[0]);
  const [confirmationText, setConfirmationText] = useState("");
  const [agreedToConsequences, setAgreedToConsequences] = useState(false);
  // Ticked on the consent screen to take the windowed deletion instead of the
  // permanent one. It changes what is submitted, not just what is shown.
  const [preferWindow, setPreferWindow] = useState(false);

  // Reset state when dialog opens/closes. Default action falls back to
  // whatever's valid for the target's current status, so a deactivated
  // target lands on "soft_delete" and an anonymized one on "hard_delete".
  useEffect(() => {
    if (!open) {
      reset();
      setAction(validActions[0]);
      setConfirmationText("");
      setAgreedToConsequences(false);
      setPreferWindow(false);
    }
  }, [open, validActions, reset]);

  const {
    data: eligibility,
    refetch: checkEligibility,
    isFetching: isCheckingEligibility,
  } = useUserDeletionEligibility(targetUser.id, open);

  const deleteUser = useOperatorDeleteUser(
    targetUser.id,
    {
      onSuccess: (data) => {
        toast.success(data.message);
        onSuccess();
        onOpenChange(false);
      },
      onError: (error: unknown) => {
        toast.error(getErrorMessage(error, "settings:operatorDeleteUser.deleteError"));
      },
    },
    caseTaskId
  );

  // Check again once the blocker is resolved inside the community.
  const refreshEligibility = async () => {
    const result = await checkEligibility();
    if (result.data?.can_delete) {
      go("confirm");
    }
  };

  // Step navigation handlers
  const handleNext = async () => {
    if (step === "choose-type") {
      go("check-blockers");
      const result = await checkEligibility();
      if (result.data?.can_delete) {
        go("confirm");
      } else if (result.data?.community_blockers.length) {
        go("resolve-blockers");
      }
    } else if (step === "check-blockers" || step === "resolve-blockers") {
      if (eligibility?.can_delete) {
        go("confirm");
      }
    }
  };

  // What is actually submitted. An operator who ticked the offer on the
  // consent screen is asking for the windowed deletion, whatever they picked
  // on the first step.
  const effectiveAction: OperatorAction =
    action === "hard_delete" && preferWindow ? "soft_delete" : action;

  const handleDelete = () => {
    deleteUser.mutate({ action: effectiveAction });
  };

  // Holding the only superadmin seat of a community is the only blocker. Owning content is not
  // one — ownership is released as the memberships go, and what they owned is
  // left for a community admin to claim.
  const hasBlockers = (eligibility?.community_blockers.length ?? 0) > 0;

  // Validation
  const canProceedFromChooseType = action !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
  // Typed back to confirm. The handle, not the address: an operator is never
  // served the whole address any more, and the masked form is full of
  // asterisks — an unusable thing to ask somebody to copy out. The handle is
  // also what the row and this dialog's own title identify the account by.
  const confirmationRequired = targetUser.username.toUpperCase();
  // The consent is asked for only where there is something to consent to: a
  // deletion that can be undone does not need somebody to say they understand
  // it cannot.
  const canConfirm =
    confirmationText === confirmationRequired &&
    (effectiveAction !== "hard_delete" || agreedToConsequences);

  const displayName = getUserDisplayName(targetUser);

  const description: Record<DeletionStep, string> = {
    "choose-type": t("operatorDeleteUser.stepType"),
    "check-blockers": t("operatorDeleteUser.checkingEligibility"),
    "resolve-blockers": t("operatorDeleteUser.stepBlockers"),
    confirm: t(
      action === "deactivate"
        ? "operatorDeleteUser.confirmDeactivateTitle"
        : action === "soft_delete"
          ? "operatorDeleteUser.confirmAnonymizeTitle"
          : "operatorDeleteUser.confirmTitle"
    ),
  };
  const walked: DeletionStep[] = hasBlockers
    ? ["choose-type", "check-blockers", "resolve-blockers", "confirm"]
    : ["choose-type", "check-blockers", "confirm"];

  return (
    <>
      <WizardDialog
        open={open}
        onOpenChange={onOpenChange}
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        title={t("operatorDeleteUser.subtitle", { email: displayName })}
        description={description[step]}
        // Resolving blockers only happens to somebody who has them, so it is
        // not counted until they are actually sent there.
        progress={{ current: walked.indexOf(step) + 1, total: walked.length }}
      >
        <div className="space-y-6 py-4">
          {/* Step 1: Choose Type */}
          {step === "choose-type" && (
            <RadioGroup
              value={action}
              onValueChange={(value) => setAction(value as OperatorAction)}
            >
              <div className="space-y-4">
                {validActions.map((option) => {
                  const meta = ACTION_META[option];
                  return (
                    <div
                      key={option}
                      className={`flex items-start space-x-3 rounded-lg border p-4 ${meta.borderClass}`}
                    >
                      <RadioGroupItem value={option} id={option} className="mt-0.5" />
                      <div className="flex-1 space-y-1">
                        <Label
                          htmlFor={option}
                          className={`cursor-pointer font-medium text-base ${meta.labelClass}`}
                        >
                          {t(meta.titleKey)}
                        </Label>
                        <p className="text-muted-foreground text-sm">{t(meta.descriptionKey)}</p>
                      </div>
                    </div>
                  );
                })}
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
                ...(eligibility?.community_blockers ?? []).map(({ community_name }) =>
                  t("operatorDeleteUser.communityBlockerTitle", { communityName: community_name })
                ),
              ]}
              blockedTitle={t("operatorDeleteUser.blockersTitle")}
              blockedHint={t("operatorDeleteUser.blockersDescription")}
              eligibleText={t("operatorDeleteUser.confirmDescription")}
            />
          )}

          {/* Step 2.5: Resolve Blockers */}
          {step === "resolve-blockers" && eligibility && (
            <div className="space-y-6">
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{t("operatorDeleteUser.blockersDescription")}</AlertDescription>
              </Alert>

              {eligibility.community_blockers.map((communityBlocker) => (
                <div
                  key={communityBlocker.community_id}
                  className="space-y-3 rounded-lg border p-4"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-medium">
                        {t("operatorDeleteUser.communityBlockerTitle", {
                          communityName: communityBlocker.community_name,
                        })}
                      </h4>
                      <p className="text-muted-foreground text-sm">
                        {t("operatorDeleteUser.communityBlockerDescription")}
                      </p>
                    </div>
                  </div>
                </div>
              ))}

              <Button
                variant="outline"
                size="sm"
                onClick={refreshEligibility}
                disabled={isCheckingEligibility}
              >
                <RefreshCw className="h-4 w-4" />
                {t("operatorDeleteUser.checkAgain")}
              </Button>

              {eligibility.can_delete && (
                <Alert className="border-green-500/50 bg-green-50 dark:bg-green-950">
                  <AlertDescription>{t("operatorDeleteUser.confirmDescription")}</AlertDescription>
                </Alert>
              )}
            </div>
          )}

          {/* Step 3: Confirm */}
          {step === "confirm" && (
            <div className="space-y-4">
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <div className="mb-2 font-semibold">
                    {t(
                      action === "deactivate"
                        ? "operatorDeleteUser.confirmDeactivateTitle"
                        : action === "soft_delete"
                          ? "operatorDeleteUser.confirmAnonymizeTitle"
                          : "operatorDeleteUser.confirmTitle"
                    )}
                  </div>
                  <p className="text-sm">
                    {t(
                      action === "deactivate"
                        ? "operatorDeleteUser.confirmDeactivate"
                        : action === "soft_delete"
                          ? "operatorDeleteUser.confirmSoftDelete"
                          : "operatorDeleteUser.confirmHardDelete",
                      { email: displayName }
                    )}
                  </p>
                </AlertDescription>
              </Alert>

              <ConfirmPhraseField
                phrase={confirmationRequired}
                value={confirmationText}
                onChange={(value) => setConfirmationText(value.toUpperCase())}
              />

              {action === "hard_delete" && (
                <div className="space-y-3">
                  <div className="flex items-start space-x-2 rounded-md border p-3">
                    <Checkbox
                      id="prefer-window"
                      className="mt-0.5"
                      checked={preferWindow}
                      onCheckedChange={(checked) => setPreferWindow(checked === true)}
                    />
                    <Label htmlFor="prefer-window" className="cursor-pointer font-normal text-sm">
                      <span className="font-medium">
                        {t("operatorDeleteUser.preferWindowLabel")}
                      </span>
                      <span className="block text-muted-foreground text-xs">
                        {t("operatorDeleteUser.preferWindowHelp")}
                      </span>
                    </Label>
                  </div>

                  {!preferWindow && (
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="agree"
                        checked={agreedToConsequences}
                        onCheckedChange={(checked) => setAgreedToConsequences(checked === true)}
                      />
                      <Label htmlFor="agree" className="cursor-pointer text-sm">
                        {t("operatorDeleteUser.confirmDescription")}
                      </Label>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <div className="flex w-full justify-between">
            <Button variant="outline" onClick={back} disabled={!canGoBack || deleteUser.isPending}>
              <ChevronLeft className="h-4 w-4" />
              {t("operatorDeleteUser.back")}
            </Button>

            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={deleteUser.isPending}
              >
                {t("operatorDeleteUser.cancel")}
              </Button>

              {step !== "confirm" ? (
                <Button
                  onClick={handleNext}
                  disabled={
                    (step === "choose-type" && !canProceedFromChooseType) ||
                    (step === "check-blockers" && !canProceedFromBlockers) ||
                    (step === "resolve-blockers" && !canProceedFromBlockers)
                  }
                  pending={isCheckingEligibility}
                >
                  {isCheckingEligibility
                    ? t("operatorDeleteUser.loading")
                    : t("operatorDeleteUser.next")}
                </Button>
              ) : (
                <Button
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={!canConfirm}
                  pending={deleteUser.isPending}
                >
                  {deleteUser.isPending
                    ? action === "deactivate"
                      ? t("operatorDeleteUser.deactivating")
                      : t("operatorDeleteUser.deleting")
                    : action === "deactivate"
                      ? t("operatorDeleteUser.deactivateButton")
                      : action === "soft_delete"
                        ? t("operatorDeleteUser.anonymizeButton")
                        : t("operatorDeleteUser.deleteButton")}
                </Button>
              )}
            </div>
          </div>
        </DialogFooter>
      </WizardDialog>
    </>
  );
}

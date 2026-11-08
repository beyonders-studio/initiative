import { QRCodeSVG } from "qrcode.react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getReadSecondFactorQueryKey,
  useBeginSecondFactor,
  useConfirmSecondFactor,
  useDisableSecondFactor,
  useReadSecondFactor,
  useRegenerateRecoveryCodes,
} from "@/api/generated/auth/auth";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { useAnnounceHeld } from "@/hooks/useHeldChange";
import { useWizard } from "@/hooks/useWizard";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import { classifySecondFactorAnswer } from "@/lib/secondFactorAnswer";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";
import { WizardDialog } from "@/ui/wizard-dialog";

/** Below this, the set is worth replacing before it runs out. */
const LOW_ON_CODES = 3;

type EnrolStep = "password" | "scan" | "codes";
/** The password step serves two errands, and they part ways after it. */
type Errand = "enrol" | "regenerate";

/**
 * Two-factor authentication, on the account's own security page.
 *
 * Three things happen here and each asks for the password again, because each
 * changes how the account is signed into. An account that holds no password —
 * provisioned through an identity provider, or signing in with a passkey — has
 * none to re-check, and the server is what says so; a recent sign-in answers
 * for it instead, so its setup starts at the code to scan.
 *
 * Setup is offered to every account wherever the deployment offers the app:
 * the code answers a community's or the deployment's ask for a second factor
 * as well as a sign-in, so an account whose sign-in never asks for it can
 * still need one.
 *
 * An account with no password keeps a set of recovery codes whether or not it
 * is enrolled here: with nothing to reset, they are how it sets a password
 * again. So the codes have a home on this section for both.
 */
export const TwoFactorSection = () => {
  const { t } = useTranslation(["settings", "errors"]);
  const announceHeld = useAnnounceHeld();
  const status = useReadSecondFactor();
  const refreshStatus = () =>
    queryClient.invalidateQueries({ queryKey: getReadSecondFactorQueryKey() });

  const [enrolOpen, setEnrolOpen] = useState(false);
  const { step, commit, reset } = useWizard<EnrolStep>("password");
  const [errand, setErrand] = useState<Errand>("enrol");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [offOpen, setOffOpen] = useState(false);
  const [offPassword, setOffPassword] = useState("");
  const [offCode, setOffCode] = useState("");

  const closeEnrol = () => {
    setEnrolOpen(false);
    // The seed and the codes exist here and nowhere else the page can reach;
    // dropping them on close is the point.
    reset();
    setErrand("enrol");
    setPassword("");
    setCode("");
    setSecret(null);
    setUri(null);
    setCodes(null);
    setError(null);
  };

  const begin = useBeginSecondFactor({
    mutation: {
      onSuccess: (data) => {
        setSecret(data.secret);
        setUri(data.otpauth_uri);
        commit("scan");
        setError(null);
        // Opened here rather than on the click, for the account that is asked
        // for no password: there is no step to show until the seed arrives.
        setEnrolOpen(true);
      },
      onError: (err) => {
        const message = getErrorMessage(err, "settings:twoFactor.enrolError");
        setError(message);
        if (!enrolOpen) toast.error(message);
      },
    },
  });

  const confirm = useConfirmSecondFactor({
    mutation: {
      onSuccess: (data) => {
        setCodes(data.codes);
        commit("codes");
        setError(null);
        void refreshStatus();
      },
      onError: (err) => {
        setError(getErrorMessage(err, "settings:twoFactor.confirmError"));
        setCode("");
      },
    },
  });

  const regenerate = useRegenerateRecoveryCodes({
    mutation: {
      onSuccess: (data) => {
        setCodes(data.codes);
        commit("codes");
        setError(null);
        // Opened here rather than on the click, for the account that is asked
        // for no password: there is no step to show until the codes arrive.
        setEnrolOpen(true);
        void refreshStatus();
      },
      onError: (err) => {
        const message = getErrorMessage(err, "settings:twoFactor.regenerateError");
        setError(message);
        if (!enrolOpen) toast.error(message);
      },
    },
  });

  const disable = useDisableSecondFactor({
    mutation: {
      onSuccess: (result) => {
        if (result.held) announceHeld(result.held);
        else toast.success(t("twoFactor.turnedOff"));
        setOffOpen(false);
        setOffPassword("");
        setOffCode("");
        void refreshStatus();
      },
      onError: (err) => setError(getErrorMessage(err, "settings:twoFactor.disableError")),
    },
  });

  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = { data: { current_password: password || null } };
    if (errand === "regenerate") {
      regenerate.mutate(body);
      return;
    }
    begin.mutate(body);
  };

  const submitCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    confirm.mutate({ data: { code: code.trim() } });
  };

  const submitDisable = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    disable.mutate({
      data: {
        current_password: offPassword || null,
        ...classifySecondFactorAnswer(offCode),
      },
    });
  };

  const enrolled = status.data?.enrolled ?? false;
  // Asked for only where there is one to give. The server is what knows:
  // an account can hold a federated identity and a password both.
  const passwordRequired = status.data?.password_required ?? true;
  // Withdrawn by whoever runs the deployment. An enrolment already made is
  // left alone and simply stops being asked for, so this says that rather than
  // offering a setup the server would refuse.
  const offered = status.data?.offered ?? true;
  const remaining = status.data?.recovery_codes_remaining ?? 0;
  // An account with no password at all. Its recovery codes are how it sets
  // one again, so they are worth showing whether or not it is enrolled here.
  const passwordless = status.data?.passwordless ?? false;

  // Re-issuing skips the authenticator app, and skips the password too where
  // there is none to re-check.
  const regenerateSteps: EnrolStep[] = passwordRequired ? ["password", "codes"] : ["codes"];
  const enrolSteps: EnrolStep[] = passwordRequired
    ? ["password", "scan", "codes"]
    : ["scan", "codes"];
  const walked: EnrolStep[] = errand === "regenerate" ? regenerateSteps : enrolSteps;

  const startEnrol = () => {
    setErrand("enrol");
    setPassword("");
    setError(null);
    reset();
    if (!passwordRequired) {
      // Nothing to re-check: a recent sign-in answers, and the dialog opens on
      // the code to scan once it is here.
      begin.mutate({ data: { current_password: null } });
      return;
    }
    setEnrolOpen(true);
  };

  const startRegenerate = () => {
    setErrand("regenerate");
    setPassword("");
    setError(null);
    reset();
    setCodes(null);
    if (!passwordRequired) {
      // Nothing to re-check, so nothing to ask: the dialog opens on the codes
      // once they are here.
      regenerate.mutate({ data: { current_password: null } });
      return;
    }
    setEnrolOpen(true);
  };

  // The same two lines wherever the set is reported — enrolled, or passwordless
  // and not.
  const codesLeftLine = (
    <p className={remaining <= LOW_ON_CODES ? "text-destructive text-sm" : "text-sm"}>
      {t("twoFactor.codesLeft", { count: remaining })}
    </p>
  );
  const newCodesButton = (
    <Button variant="outline" onClick={startRegenerate} disabled={regenerate.isPending}>
      {t("twoFactor.regenerate")}
    </Button>
  );

  return (
    <div className="space-y-4">
      {status.isLoading ? (
        <SkeletonRegion>
          <SkeletonLines lines={2} />
        </SkeletonRegion>
      ) : status.isError ? (
        // Unknown is not the same as off: offering setup here would send an
        // enrolled account to a dead end.
        <StatusMessage onRetry={status.refetch} />
      ) : enrolled ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{t("twoFactor.on")}</Badge>
            {status.data?.confirmed_at ? (
              <span className="text-muted-foreground text-sm">
                {t("twoFactor.addedOn", {
                  date: formatDateTime(status.data.confirmed_at),
                })}
              </span>
            ) : null}
          </div>
          <p className="text-muted-foreground text-sm">
            {status.data?.last_used_at
              ? t("twoFactor.lastUsed", { date: formatDateTime(status.data.last_used_at) })
              : t("twoFactor.neverUsed")}
          </p>
          {codesLeftLine}
          <div className="flex flex-wrap gap-2">
            {newCodesButton}
            <Button
              variant="destructive"
              onClick={() => {
                setError(null);
                setOffOpen(true);
              }}
            >
              {t("twoFactor.turnOff")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-muted-foreground text-sm">
            {offered ? t("twoFactor.notSetUp") : t("twoFactor.notOffered")}
          </p>
          {offered ? (
            <Button onClick={startEnrol} disabled={begin.isPending}>
              {t("twoFactor.setUp")}
            </Button>
          ) : null}
          {passwordless ? (
            <div className="space-y-3 border-t pt-3">
              <p className="text-muted-foreground text-sm">{t("twoFactor.passwordlessCodes")}</p>
              {codesLeftLine}
              {newCodesButton}
            </div>
          ) : null}
        </div>
      )}

      <WizardDialog
        open={enrolOpen}
        onOpenChange={(open) => (open ? setEnrolOpen(true) : closeEnrol())}
        title={
          step === "codes"
            ? t("twoFactor.codesTitle")
            : errand === "regenerate"
              ? t("twoFactor.regenerateTitle")
              : t("twoFactor.setUpTitle")
        }
        description={
          step === "password"
            ? errand === "regenerate"
              ? t("twoFactor.regeneratePrompt")
              : t("twoFactor.passwordPrompt")
            : step === "scan"
              ? t("twoFactor.scanPrompt")
              : t("twoFactor.codesPrompt")
        }
        // Re-issuing codes skips the authenticator app: there is nothing new
        // to scan, so it is two screens rather than three.
        progress={{ current: walked.indexOf(step) + 1, total: walked.length }}
      >
        {step === "password" ? (
          <form className="space-y-4" onSubmit={submitPassword}>
            <Field label={t("twoFactor.passwordLabel")}>
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </Field>
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" disabled={begin.isPending || regenerate.isPending}>
                {t("twoFactor.continue")}
              </Button>
            </DialogFooter>
          </form>
        ) : null}

        {step === "scan" && uri && secret ? (
          <form className="space-y-4" onSubmit={submitCode}>
            {/* Always dark on white: a scanner wants contrast, not the page's
                  palette. */}
            <div className="flex justify-center rounded-md bg-white p-4">
              <QRCodeSVG value={uri} size={176} />
            </div>
            <div className="space-y-1">
              <p className="text-muted-foreground text-sm">{t("twoFactor.cannotScan")}</p>
              <code className="block break-all rounded bg-muted px-2 py-1 font-mono text-sm">
                {secret}
              </code>
            </div>
            <Field label={t("twoFactor.codeLabel")}>
              <Input
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder={t("twoFactor.codePlaceholder")}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                required
              />
            </Field>
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" disabled={confirm.isPending || !code.trim()}>
                {t("twoFactor.turnOn")}
              </Button>
            </DialogFooter>
          </form>
        ) : null}

        {step === "codes" && codes ? (
          <RecoveryCodesPanel
            codes={codes}
            note={t("twoFactor.codesWarning")}
            onDone={closeEnrol}
          />
        ) : null}
      </WizardDialog>

      <Dialog open={offOpen} onOpenChange={setOffOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("twoFactor.turnOffTitle")}</DialogTitle>
            <DialogDescription>{t("twoFactor.turnOffPrompt")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitDisable}>
            {passwordRequired ? (
              <Field label={t("twoFactor.passwordLabel")}>
                <Input
                  type="password"
                  autoComplete="current-password"
                  value={offPassword}
                  onChange={(event) => setOffPassword(event.target.value)}
                  required
                />
              </Field>
            ) : null}
            <Field label={t("twoFactor.codeOrRecoveryLabel")}>
              <Input
                autoComplete="one-time-code"
                value={offCode}
                onChange={(event) => setOffCode(event.target.value)}
                required
              />
            </Field>
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" variant="destructive" disabled={disable.isPending}>
                {t("twoFactor.turnOff")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

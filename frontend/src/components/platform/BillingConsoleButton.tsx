/**
 * Opens one community in the billing portal.
 *
 * The visit is authorised by a billing grant, which reaches the billing
 * account and nothing in the community. A live one is reused; otherwise the
 * server issues one, and asks for the account's second factor first, the way
 * breaking glass does. That ask arrives as a refusal, and this button answers
 * it with a dialog and tries again.
 */

import { Capacitor } from "@capacitor/core";
import { type ComponentProps, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SecondFactorAnswer } from "@/api/generated/initiativeAPI.schemas";
import { createPlatformCommunityBillingServiceHandoff } from "@/api/generated/settings/settings";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useBreakGlassRequirements } from "@/hooks/useAccessGrants";
import { useAppConfig } from "@/hooks/useAppConfig";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { openExternal, reserveTab } from "@/lib/openExternal";
import { assertForBreakGlass, describePasskeyPromptError, passkeysRunHere } from "@/lib/passkeys";
import { classifySecondFactorAnswer } from "@/lib/secondFactorAnswer";

type BillingConsole = "support" | "operator";

/** The billing portal is opened from the website and the other apps, never from the iPhone app. */
export const opensBillingHere = () => Capacitor.getPlatform() !== "ios";

export const BillingConsoleButton = ({
  community,
  console,
  children,
  ...buttonProps
}: {
  community: { id: number; name: string };
  console: BillingConsole;
  children: ReactNode;
} & Omit<ComponentProps<typeof Button>, "onClick" | "children">) => {
  const { i18n } = useTranslation("settings");
  const { billing } = useAppConfig();
  const [opening, setOpening] = useState(false);
  const [asking, setAsking] = useState(false);

  const open = async (answer: SecondFactorAnswer | null) => {
    if (!billing) return;
    setOpening(true);
    // Opened inside the click, before the request, so it is not a popup.
    const tab = reserveTab();
    try {
      const { handoff_token } = await createPlatformCommunityBillingServiceHandoff(
        community.id,
        answer,
        { console }
      );
      const lang = i18n.resolvedLanguage ?? i18n.language;
      // The token rides in the fragment, which never leaves the browser. The
      // console reads the community off the exchanged session, so the URL does not
      // name one — only the language carries over.
      const url = `${billing.url}/${console}?lang=${encodeURIComponent(
        lang
      )}#${console}_handoff=${encodeURIComponent(handoff_token)}`;
      openExternal(url, tab);
      setAsking(false);
    } catch (err) {
      tab?.close();
      if (getErrorCode(err) === "ACCESS_GRANT_SECOND_FACTOR_REQUIRED") {
        setAsking(true);
        return;
      }
      toast.error(getErrorMessage(err, "settings:communities.billing.openError"));
    } finally {
      setOpening(false);
    }
  };

  if (!opensBillingHere()) {
    return <span className="text-sm">{children}</span>;
  }

  return (
    <>
      <Button {...buttonProps} onClick={() => void open(null)} disabled={opening}>
        {children}
      </Button>
      {asking ? (
        <SecondFactorDialog
          communityName={community.name}
          busy={opening}
          onAnswer={(answer) => void open(answer)}
          onOpenChange={setAsking}
        />
      ) : null}
    </>
  );
};

const SecondFactorDialog = ({
  communityName,
  busy,
  onAnswer,
  onOpenChange,
}: {
  communityName: string;
  busy: boolean;
  onAnswer: (answer: SecondFactorAnswer) => void;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common", "auth"]);
  const requirements = useBreakGlassRequirements();
  const [code, setCode] = useState("");
  const [presenting, setPresenting] = useState(false);
  const hasCode = requirements.data?.totp_enrolled ?? false;
  const hasKey = requirements.data?.passkey_enrolled ?? false;
  const knownUnenrolled = requirements.data !== undefined && !hasCode && !hasKey;

  const presentAKey = async () => {
    setPresenting(true);
    try {
      onAnswer({ passkey: await assertForBreakGlass() });
    } catch (err) {
      const line = describePasskeyPromptError(err);
      if (line) toast.error(t(line));
    } finally {
      setPresenting(false);
    }
  };

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("communities.billing.factor.title")}</DialogTitle>
          <DialogDescription>
            {t("communities.billing.factor.description", { name: communityName })}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const entered = code.trim();
            if (entered) onAnswer(classifySecondFactorAnswer(entered));
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="billing-factor-code">{t("accessGrants.breakGlass.codeLabel")}</Label>
            <Input
              id="billing-factor-code"
              autoComplete="one-time-code"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder={t("accessGrants.breakGlass.codePlaceholder")}
            />
            <p className="text-muted-foreground text-xs">
              {knownUnenrolled
                ? t("accessGrants.breakGlass.codeNotEnrolled")
                : t("accessGrants.breakGlass.codeHelp")}
            </p>
          </div>
          <DialogFooter className="flex-wrap gap-2">
            {hasKey && passkeysRunHere() ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void presentAKey()}
                disabled={busy || presenting}
              >
                {presenting
                  ? t("accessGrants.breakGlass.passkeyPresenting")
                  : t("accessGrants.breakGlass.passkeySubmit")}
              </Button>
            ) : null}
            <Button type="submit" disabled={busy || presenting || !code.trim()}>
              {busy ? t("common:submitting") : t("communities.billing.factor.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

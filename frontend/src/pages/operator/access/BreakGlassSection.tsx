import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { BreakGlassCreate, CommunityNotice } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useBreakGlass, useBreakGlassRequirements } from "@/hooks/useAccessGrants";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { assertForBreakGlass, describePasskeyPromptError, passkeysRunHere } from "@/lib/passkeys";
import { classifySecondFactorAnswer } from "@/lib/secondFactorAnswer";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

import { CommunityPicker, type PickedCommunity } from "./CommunityPicker";
import {
  CaseField,
  CommunityNoticeField,
  durationsUpTo,
  formCommunity,
  noticeChoice,
  useCaseChoice,
  usePreselectedCommunity,
} from "./grantForm";

// Break-glass duration presets (whole hours), offered up to the window the
// server says the caller may break glass for — a self-approved grant is
// deliberately short.
const BREAK_GLASS_DURATIONS_MINUTES = [60, 120, 240];

// Self-serve emergency access for data.bypass holders (operator/owner). Unlike a
// request, this is approved on creation — live immediately, scoped to one community,
// read-only by default, short-lived, and recorded as an audited grant.
/** The server saying this request had to carry the account's second factor. */
const isSecondFactorRefusal = (error: unknown): boolean =>
  (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail ===
  "ACCESS_GRANT_SECOND_FACTOR_REQUIRED";

export const BreakGlassSection = () => {
  // auth too: a prompt that produced nothing is reported in the same words
  // the sign-in page uses for it.
  const { t } = useTranslation(["settings", "common", "auth"]);
  const { refreshCommunities } = useCommunities();
  const preselected = usePreselectedCommunity("break_glass");
  const [pickedCommunity, setCommunity] = useState<PickedCommunity | null>(preselected);
  const caseChoice = useCaseChoice("break_glass");
  const community = formCommunity(pickedCommunity, caseChoice.chosen);
  // Null until chosen: the offered windows arrive with the requirements below.
  const [chosenDuration, setDuration] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<CommunityNotice>("none");
  const [code, setCode] = useState("");

  // What this request will be asked for. Breaking glass carries the account's
  // own second factor once any data.bypass holder has one, so the form asks
  // here rather than guessing from the caller's own enrolment.
  //
  // The answer can change while this page is open — somebody else enrolling is
  // all it takes — so the server stays the authority: a refusal naming the
  // factor reveals the field and refetches, rather than the form insisting on
  // what it last heard.
  const requirements = useBreakGlassRequirements();
  const [factorRefused, setFactorRefused] = useState(false);
  const needsCode = (requirements.data?.second_factor_required ?? false) || factorRefused;
  // Either factor answers, so the form offers what this account actually
  // holds: the code field, the key, or the line telling somebody with neither
  // where to go and get one.
  const hasCode = requirements.data?.totp_enrolled ?? false;
  const hasKey = requirements.data?.passkey_enrolled ?? false;
  const knownUnenrolled = requirements.data !== undefined && !hasCode && !hasKey;
  const [presenting, setPresenting] = useState(false);
  const breakGlassDurations = durationsUpTo(
    BREAK_GLASS_DURATIONS_MINUTES,
    requirements.data?.max_duration_minutes
  );
  const duration = chosenDuration ?? String(breakGlassDurations[0] ?? "");

  const breakGlass = useBreakGlass({
    onSuccess: () => {
      toast.success(t("accessGrants.breakGlass.activated"));
      setCommunity(null);
      caseChoice.setCaseTaskId(null);
      setReason("");
      setNotice("none");
      setCode("");
      setFactorRefused(false);
      setPresenting(false);
      setDuration(null);
      // A break-glass grant is live immediately. The community switcher and the
      // /c/{id} route guard read from the CommunityProvider's context list (not
      // React Query), so refresh it here — otherwise the newly-reachable community
      // doesn't appear until a manual reload.
      void refreshCommunities();
    },
    onError: (err) => {
      if (isSecondFactorRefusal(err)) {
        setFactorRefused(true);
        void requirements.refetch();
      }
      toast.error(getErrorMessage(err, "settings:accessGrants.breakGlass.error"));
    },
  });

  /** The request itself, with whatever answered the factor attached. */
  const issue = (answer: Partial<BreakGlassCreate>) => {
    if (!community || !reason.trim() || !duration) return;
    // No level to choose: breaking glass issues write access to the content
    // and a settings grant at superadmin. Somebody who wants less asks below.
    breakGlass.mutate({
      community_id: community.id,
      reason: reason.trim(),
      requested_duration_minutes: Number.parseInt(duration, 10),
      ...(caseChoice.caseTaskId == null ? {} : { case_task_id: caseChoice.caseTaskId }),
      ...noticeChoice(caseChoice.chosen, notice),
      ...answer,
    });
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const entered = code.trim();
    issue(needsCode && entered ? classifySecondFactorAnswer(entered) : {});
  };

  /** Answer with a key instead. The ceremony runs first and the assertion it
   *  produces goes out with the request, so the key answers this grant rather
   *  than the session the button was pressed on. */
  const presentAKey = async () => {
    if (!community || !reason.trim()) return;
    setPresenting(true);
    try {
      issue({ passkey: await assertForBreakGlass() });
    } catch (err) {
      const line = describePasskeyPromptError(err);
      if (line) toast.error(t(line));
    } finally {
      setPresenting(false);
    }
  };

  return (
    <SettingsSection
      title={t("accessGrants.breakGlass.title")}
      description={t("accessGrants.breakGlass.description")}
      className="border-destructive/50"
    >
      <form className="grid grid-cols-pair gap-4" onSubmit={submit}>
        <Field label={t("accessGrants.communityLabel")} className="space-y-1">
          <CommunityPicker
            aria-label={t("accessGrants.communityLabel")}
            value={community}
            onChange={setCommunity}
          />
        </Field>
        <CaseField choice={caseChoice} community={community} optional />
        <CommunityNoticeField
          id="bg-notice"
          chosen={caseChoice.chosen}
          value={notice}
          onChange={setNotice}
        />
        <Field label={t("accessGrants.durationLabel")} className="space-y-1">
          <Select value={duration} onValueChange={setDuration}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {breakGlassDurations.map((minutes) => (
                <SelectItem key={minutes} value={String(minutes)}>
                  {t("accessGrants.durationHours", { count: minutes / 60 })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("accessGrants.reasonLabel")} className="col-span-full space-y-1">
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("accessGrants.breakGlass.reasonPlaceholder")}
            required
          />
        </Field>
        {needsCode && (
          <Field
            label={t("accessGrants.breakGlass.codeLabel")}
            hint={
              knownUnenrolled
                ? t("accessGrants.breakGlass.codeNotEnrolled")
                : t("accessGrants.breakGlass.codeHelp")
            }
            className="col-span-full space-y-1"
          >
            <Input
              autoComplete="one-time-code"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={t("accessGrants.breakGlass.codePlaceholder")}
              required
            />
          </Field>
        )}
        <div className="col-span-full flex flex-wrap gap-2">
          <Button
            type="submit"
            variant="destructive"
            disabled={!community || breakGlass.isPending || presenting}
          >
            {breakGlass.isPending ? t("common:submitting") : t("accessGrants.breakGlass.submit")}
          </Button>
          {needsCode && hasKey && passkeysRunHere() && (
            <Button
              type="button"
              variant="outline"
              onClick={() => void presentAKey()}
              disabled={!community || breakGlass.isPending || presenting}
            >
              {presenting
                ? t("accessGrants.breakGlass.passkeyPresenting")
                : t("accessGrants.breakGlass.passkeySubmit")}
            </Button>
          )}
        </div>
      </form>
    </SettingsSection>
  );
};

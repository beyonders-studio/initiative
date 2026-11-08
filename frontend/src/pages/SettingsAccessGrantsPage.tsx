import { useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AccessGrantRead,
  BreakGlassCreate,
  CommunityNotice,
  GrantCaseRead,
} from "@/api/generated/initiativeAPI.schemas";
import { AccessGrantStatusBadge } from "@/components/platform/AccessGrantStatusBadge";
import { CasePicker } from "@/components/platform/CasePicker";
import { CommunityPicker, type PickedCommunity } from "@/components/platform/CommunityPicker";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { UserHandle } from "@/components/UserHandle";
import {
  flattenGrants,
  useAccessGrantLimits,
  useAccessGrantQueue,
  useApproveAccessGrant,
  useBreakGlass,
  useBreakGlassRequirements,
  useCancelAccessRequest,
  useCreateAccessRequest,
  useDenyAccessGrant,
  useGrantCases,
  useMyAccessGrants,
  useRevokeAccessGrant,
} from "@/hooks/useAccessGrants";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import type { AccessGrantsForm, AccessGrantsSearch } from "@/lib/accessGrantsSearch";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { assertForBreakGlass, describePasskeyPromptError, passkeysRunHere } from "@/lib/passkeys";
import { Capability, hasCapability } from "@/lib/permissions";
import { classifySecondFactorAnswer } from "@/lib/secondFactorAnswer";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { minutesLeft } from "@/ui/lib/formatDate";
import { LoadMore } from "@/ui/load-more";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

// Always surface the community id alongside the name so approvers can
// disambiguate similarly-named communities (and fall back cleanly when the name
// isn't populated).
/** Who holds a grant: their handle, or their account number where the
 *  account is gone. Never their address. */
const GrantHolder = ({ grant }: { grant: AccessGrantRead }) =>
  grant.user ? <UserHandle user={grant.user} /> : <>{getUserDisplayName({ id: grant.user_id })}</>;

const communityLabel = (grant: { community_name?: string | null; community_id: number }): string =>
  grant.community_name
    ? `${grant.community_name} (#${grant.community_id})`
    : `#${grant.community_id}`;

// Float the actionable grants to the top so they're never buried under dead
// history: pending (you can cancel) first, then live (currently usable), then
// everything else. Stable over the backend's newest-first ordering.
const activityRank = (grant: AccessGrantRead): number => {
  if (grant.status === "pending") return 0;
  if (grant.is_live) return 1;
  return 2;
};

// All whole-hour presets for a request, ascending.
const DURATION_PRESETS_MINUTES = [60, 240, 480, 1440];

/**
 * The presets up to the server's ceiling for this caller, and the ceiling
 * itself where it is not one of them. The server enforces the ceiling; this
 * only decides which windows to offer.
 */
const durationsUpTo = (presets: number[], max: number | undefined): number[] => {
  if (max === undefined) return [];
  const offered = presets.filter((minutes) => minutes <= max);
  return offered.includes(max) ? offered : [...offered, max];
};

/**
 * The community a form starts with, when the page was opened for that form
 * from a row on the Communities tab.
 */
const usePreselectedCommunity = (form: AccessGrantsForm): PickedCommunity | null => {
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  if (!search.community || search.form !== form) return null;
  return { id: search.community, name: search.name ?? null };
};

/**
 * The operations case a form is for: the open cases on offer, whether one must
 * be named, and the one chosen, starting from the case the page was opened
 * for when it was opened for this form.
 */
const useCaseChoice = (form: AccessGrantsForm) => {
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  const cases = useGrantCases();
  const [caseTaskId, setChosenId] = useState<number | null>(
    search.form === form ? (search.case ?? null) : null
  );
  // A case a search found is not in the first page, so it is kept as chosen.
  const [found, setFound] = useState<GrantCaseRead | undefined>(undefined);
  const items = cases.data?.items ?? [];
  const setCaseTaskId = (taskId: number | null, picked?: GrantCaseRead) => {
    setChosenId(taskId);
    setFound(picked);
  };
  const listed =
    caseTaskId == null
      ? undefined
      : (items.find((item) => item.task_id === caseTaskId) ??
        (found?.task_id === caseTaskId ? found : undefined));
  // A case the page was opened for that is past the first page is looked up
  // by its number, so the form knows what it allows.
  const lookedUp = useGrantCases({
    enabled: caseTaskId != null && cases.isSuccess && listed === undefined,
    search: `#${caseTaskId}`,
  });
  return {
    items,
    loading: cases.isLoading,
    loaded: cases.isSuccess,
    required: cases.data?.required ?? false,
    caseTaskId,
    setCaseTaskId,
    chosen: listed ?? lookedUp.data?.items.find((item) => item.task_id === caseTaskId),
  };
};

type CaseChoice = ReturnType<typeof useCaseChoice>;

/**
 * The community a form asks about: the one picked, or else the one the chosen
 * case is about.
 */
const formCommunity = (
  picked: PickedCommunity | null,
  chosen: GrantCaseRead | undefined
): PickedCommunity | null =>
  picked ?? (chosen?.subject_community_id != null ? { id: chosen.subject_community_id } : null);

/** The case picker, what it asks of the form, and a word where the community
 *  picked is not the one the case is about. The server decides; this only
 *  says so before it is asked. */
const CaseField = ({
  choice,
  community,
  optional,
}: {
  choice: CaseChoice;
  community: PickedCommunity | null;
  optional: boolean;
}) => {
  const { t } = useTranslation("settings");
  const subject = choice.chosen?.subject_community_id ?? null;
  const otherCommunity = subject != null && community != null && community.id !== subject;
  let hint: string | null = null;
  if (choice.caseTaskId == null) {
    if (optional) hint = t("accessGrants.caseOptionalHint");
    else if (choice.required) {
      hint =
        choice.loaded && choice.items.length === 0
          ? t("accessGrants.caseRequiredNoneOpen")
          : t("accessGrants.caseRequiredHint");
    }
  }
  return (
    <Field label={t("accessGrants.caseLabel")} hint={hint} className="space-y-1">
      <CasePicker
        cases={choice.items}
        value={choice.caseTaskId}
        onChange={choice.setCaseTaskId}
        optional={optional || !choice.required}
        loading={choice.loading}
      />
      {otherCommunity ? (
        <p className="text-warning text-xs">
          {t("accessGrants.caseOtherCommunity", { community: subject })}
        </p>
      ) : null}
    </Field>
  );
};

/**
 * Whether the community is told of the access, as the chosen case allows: a
 * support case always tells it when access starts, and a security or
 * moderation case leaves it to the asker. The server settles it; this only
 * offers what it will take.
 */
const CommunityNoticeField = ({
  id,
  chosen,
  value,
  onChange,
}: {
  id: string;
  chosen: GrantCaseRead | undefined;
  value: CommunityNotice;
  onChange: (value: CommunityNotice) => void;
}) => {
  const { t } = useTranslation("settings");
  if (chosen?.community_notice === "always") {
    return (
      <p className="col-span-full text-muted-foreground text-xs">
        {t("accessGrants.notice.always")}
      </p>
    );
  }
  if (chosen?.community_notice !== "optional") return null;
  return (
    <Field
      label={t("accessGrants.notice.label")}
      hint={t("accessGrants.notice.help")}
      id={id}
      className="space-y-1"
    >
      <Select value={value} onValueChange={(next) => onChange(next as CommunityNotice)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">{t("accessGrants.notice.none")}</SelectItem>
          <SelectItem value="when_granted">{t("accessGrants.notice.when_granted")}</SelectItem>
          <SelectItem value="when_ended">{t("accessGrants.notice.when_ended")}</SelectItem>
        </SelectContent>
      </Select>
    </Field>
  );
};

/** What a form sends for the community's notice: a choice only where the
 *  chosen case offers one. */
const noticeChoice = (chosen: GrantCaseRead | undefined, notice: CommunityNotice) =>
  chosen?.community_notice === "optional" && notice !== "none" ? { community_notice: notice } : {};

/** The case a grant was asked for, by its number, and when its community is
 *  told of it. */
const GrantCaseMark = ({ grant }: { grant: AccessGrantRead }) => {
  const { t } = useTranslation("settings");
  if (grant.case_task_id == null) return null;
  // Reaching the case needs the operations community's address, which this
  // page does not hold, so the number stands alone.
  return (
    <span className="shrink-0 text-muted-foreground text-xs">
      {t("accessGrants.caseMark", { id: grant.case_task_id })}
      {grant.community_notice !== "none"
        ? ` · ${t(`accessGrants.notice.mark.${grant.community_notice}`)}`
        : null}
    </span>
  );
};

export const SettingsAccessGrantsPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const canRequest = hasCapability(user, Capability.accessRequest);
  const canApprove = hasCapability(user, Capability.accessApprove);
  const canBreakGlass = hasCapability(user, Capability.dataBypass);

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground">{t("accessGrants.description")}</p>
      {canApprove && <ApprovalQueue />}
      {canBreakGlass && <BreakGlassSection />}
      {canRequest && <RequestSection />}
    </div>
  );
};

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

/** What a grant is for and how far it goes, in one phrase — the level alone is
 *  ambiguous now that a settings grant carries its own vocabulary. */
const grantScope = (grant: { purpose?: string; access_level: string }): string =>
  grant.purpose === "settings" ? `settings · ${grant.access_level}` : grant.access_level;

const BreakGlassSection = () => {
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

/** The content rung the request form starts on: the one the link that opened
 *  it named, where the reader may ask for it, and read-only otherwise. A
 *  moderator, who asks for nothing else, starts on moderate. */
const startingLevel = (
  search: AccessGrantsSearch,
  canModerate: boolean,
  canAskAny: boolean
): string => {
  if (!canAskAny) return "moderate";
  if (search.form !== "request" || !search.level) return "read";
  return search.level === "moderate" && !canModerate ? "read" : search.level;
};

const RequestSection = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  // Reading what the platform holds is moderation work: only those who
  // moderate content may ask for it.
  const canModerate = hasCapability(user, Capability.contentModerate);
  // Everything else — read, read-write, settings — is access.request_any's: a
  // moderator asks for moderation access alone.
  const canAskAny = hasCapability(user, Capability.accessRequestAny);
  const myGrants = useMyAccessGrants();
  const limits = useAccessGrantLimits();
  const sortedGrants = useMemo(
    () => flattenGrants(myGrants.data?.pages).sort((a, b) => activityRank(a) - activityRank(b)),
    [myGrants.data]
  );
  const durationOptions = durationsUpTo(
    DURATION_PRESETS_MINUTES,
    limits.data?.max_duration_minutes
  );
  const defaultDuration = String(durationOptions.includes(240) ? 240 : (durationOptions[0] ?? ""));
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  const preselected = usePreselectedCommunity("request");
  const [pickedCommunity, setCommunity] = useState<PickedCommunity | null>(preselected);
  const caseChoice = useCaseChoice("request");
  const community = formCommunity(pickedCommunity, caseChoice.chosen);
  // Two axes, asked for independently. "none" is how you say you do not want
  // one — clearing up after an incident wants both; having a look wants only
  // the first.
  const [level, setLevel] = useState<string>(() => startingLevel(search, canModerate, canAskAny));
  const [settingsLevel, setSettingsLevel] = useState("none");
  // Null until chosen: the offered windows arrive with the limits above.
  const [chosenDuration, setDuration] = useState<string | null>(null);
  const duration = chosenDuration ?? defaultDuration;
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<CommunityNotice>("none");

  const createRequest = useCreateAccessRequest({
    onSuccess: () => {
      toast.success(t("accessGrants.requestSubmitted"));
      setCommunity(null);
      caseChoice.setCaseTaskId(null);
      setReason("");
      setNotice("none");
      setDuration(null);
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.requestError")),
  });
  const cancelRequest = useCancelAccessRequest({
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.cancelError")),
  });

  // A request must name at least one authority.
  const asksForSomething = level !== "none" || settingsLevel !== "none";
  // And, where the deployment says so, the case it is for.
  const namesItsCase = !caseChoice.required || caseChoice.caseTaskId != null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!community || !reason.trim() || !asksForSomething || !namesItsCase || !duration) return;
    createRequest.mutate({
      community_id: community.id,
      ...(level === "none" ? {} : { access_level: level as "read" | "read_write" | "moderate" }),
      ...(settingsLevel === "none"
        ? {}
        : { settings_level: settingsLevel as "admin" | "superadmin" }),
      reason: reason.trim(),
      requested_duration_minutes: Number.parseInt(duration, 10),
      ...(caseChoice.caseTaskId == null ? {} : { case_task_id: caseChoice.caseTaskId }),
      ...noticeChoice(caseChoice.chosen, notice),
    });
  };

  return (
    <SettingsSection
      title={t("accessGrants.requestTitle")}
      description={t("accessGrants.requestDescription")}
    >
      <form className="grid grid-cols-pair gap-4" onSubmit={submit}>
        <Field label={t("accessGrants.communityLabel")} className="space-y-1">
          <CommunityPicker
            aria-label={t("accessGrants.communityLabel")}
            value={community}
            onChange={setCommunity}
          />
        </Field>
        <CaseField choice={caseChoice} community={community} optional={false} />
        <CommunityNoticeField
          id="ag-notice"
          chosen={caseChoice.chosen}
          value={notice}
          onChange={setNotice}
        />
        <Field
          label={t("accessGrants.purposeContent")}
          hint={t("accessGrants.purposeContentHelp")}
          className="space-y-1"
        >
          <Select value={level} onValueChange={setLevel}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {canAskAny ? (
                <>
                  <SelectItem value="none">{t("accessGrants.levelNone")}</SelectItem>
                  <SelectItem value="read">{t("accessGrants.levelRead")}</SelectItem>
                  <SelectItem value="read_write">{t("accessGrants.levelReadWrite")}</SelectItem>
                </>
              ) : null}
              {canModerate ? (
                <SelectItem value="moderate">{t("accessGrants.levelModerate")}</SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </Field>
        {canAskAny ? (
          <Field
            label={t("accessGrants.purposeSettings")}
            hint={t("accessGrants.purposeSettingsHelp")}
            className="space-y-1"
          >
            <Select value={settingsLevel} onValueChange={setSettingsLevel}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("accessGrants.levelNone")}</SelectItem>
                <SelectItem value="admin">{t("accessGrants.levelAdmin")}</SelectItem>
                <SelectItem value="superadmin">{t("accessGrants.levelSuperadmin")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        ) : null}
        <Field label={t("accessGrants.durationLabel")} className="space-y-1">
          <Select value={duration} onValueChange={setDuration}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {durationOptions.map((minutes) => (
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
            placeholder={t("accessGrants.reasonPlaceholder")}
            required
          />
        </Field>
        <div className="col-span-full">
          <Button
            type="submit"
            disabled={!community || createRequest.isPending || !asksForSomething || !namesItsCase}
          >
            {createRequest.isPending ? t("common:submitting") : t("accessGrants.submitRequest")}
          </Button>
          {!asksForSomething && (
            <p className="mt-2 text-muted-foreground text-xs">{t("accessGrants.nothingAsked")}</p>
          )}
        </div>
      </form>

      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.myRequests")}</h3>
        {!sortedGrants.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noRequests")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {sortedGrants.map((grant) => {
              const left = minutesLeft(grant.expires_at);
              return (
                <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      {communityLabel(grant)} · {grantScope(grant)}
                    </p>
                    <p className="flex gap-2 text-muted-foreground text-xs">
                      <GrantCaseMark grant={grant} />
                      <span className="truncate">{grant.reason}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {grant.is_live && left !== null && (
                      <span className="text-muted-foreground text-xs">
                        {t("accessGrants.expiresIn", { minutes: left })}
                      </span>
                    )}
                    <AccessGrantStatusBadge grant={grant} />
                    {grant.status === "pending" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => cancelRequest.mutate(grant.id)}
                        disabled={cancelRequest.isPending}
                      >
                        {t("common:cancel")}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={myGrants.hasNextPage}
          loading={myGrants.isFetchingNextPage}
          onLoadMore={myGrants.fetchNextPage}
        />
      </div>
    </SettingsSection>
  );
};

const ApprovalQueue = () => {
  const { t } = useTranslation(["settings", "common"]);
  const pending = useAccessGrantQueue("pending");
  // Server-side ``live`` filter so paging the active list is accurate (no
  // client-side is_live filtering that would leave pages partially empty).
  const active = useAccessGrantQueue("approved", { live: true });
  const pendingItems = flattenGrants(pending.data?.pages);
  const activeItems = flattenGrants(active.data?.pages);

  const approve = useApproveAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.approved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });
  const deny = useDenyAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.denied")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });
  const revoke = useRevokeAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.revoked")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });

  return (
    <SettingsSection
      title={t("accessGrants.queueTitle")}
      description={t("accessGrants.queueDescription")}
      contentClassName="space-y-5"
    >
      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.pendingHeading")}</h3>
        {!pendingItems.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noPending")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {pendingItems.map((grant) => (
              <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="truncate text-sm">
                    <GrantHolder grant={grant} /> → {communityLabel(grant)} · {grantScope(grant)} ·{" "}
                    {t("accessGrants.minutes", { minutes: grant.requested_duration_minutes })}
                  </p>
                  <p className="flex gap-2 text-muted-foreground text-xs">
                    <GrantCaseMark grant={grant} />
                    <span className="truncate">{grant.reason}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => approve.mutate({ grantId: grant.id })}
                    disabled={approve.isPending}
                  >
                    {t("accessGrants.approve")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => deny.mutate(grant.id)}
                    disabled={deny.isPending}
                  >
                    {t("accessGrants.deny")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={pending.hasNextPage}
          loading={pending.isFetchingNextPage}
          onLoadMore={pending.fetchNextPage}
        />
      </div>

      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.activeHeading")}</h3>
        {!activeItems.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noActive")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {activeItems.map((grant) => {
              const left = minutesLeft(grant.expires_at);
              return (
                <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      <GrantHolder grant={grant} /> → {communityLabel(grant)} · {grantScope(grant)}
                    </p>
                    {(left !== null || grant.case_task_id != null) && (
                      <p className="flex gap-2 text-muted-foreground text-xs">
                        <GrantCaseMark grant={grant} />
                        {left !== null && (
                          <span>{t("accessGrants.expiresIn", { minutes: left })}</span>
                        )}
                      </p>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => revoke.mutate(grant.id)}
                    disabled={revoke.isPending}
                  >
                    {t("accessGrants.revoke")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={active.hasNextPage}
          loading={active.isFetchingNextPage}
          onLoadMore={active.fetchNextPage}
        />
      </div>
    </SettingsSection>
  );
};

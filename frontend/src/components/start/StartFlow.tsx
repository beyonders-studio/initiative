/**
 * The start flow: what somebody came for, then what that answer needs.
 *
 * Four paths — an invite, joining a listed community, a space of one's own,
 * a community for a group — and only the ones this deployment can honour are
 * offered. Signed out, the flow ends by making the account, which carries the
 * community with it. Signed in with no community, it is the same questions
 * without the account, and ends by making the community.
 *
 * Every question has an answer already filled in, so Continue always works;
 * only what an account cannot be made without (an address, a handle, a way to
 * sign in) has to be typed.
 *
 * This file holds the order of the steps and what finishing does; each step's
 * form is its own component beside it, and Yonder hosts every one.
 */

import { Link, useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBootstrapStatus } from "@/api/generated/auth/auth";
import { getInviteStatus } from "@/api/generated/communities/communities";
import type { CommunityInviteStatus, CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { EmailOtpCard } from "@/components/auth/EmailOtpCard";
import { ServerChip, ServerPicker } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { AccountStep } from "@/components/start/AccountStep";
import { ChooseStep } from "@/components/start/ChooseStep";
import { CommunityStep } from "@/components/start/CommunityStep";
import { InterestStep } from "@/components/start/InterestStep";
import { InviteStep } from "@/components/start/InviteStep";
import { PeopleStep } from "@/components/start/PeopleStep";
import { PlanStep } from "@/components/start/PlanStep";
import { ContinueButton } from "@/components/start/stepParts";
import { useSignUp } from "@/components/start/useSignUp";
import { type YonderPose, YonderSays } from "@/components/start/YonderSays";
import { YouStep } from "@/components/start/YouStep";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useBillingCatalog } from "@/hooks/useBillingCatalog";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import {
  firstHomeContext,
  useLandOnStarter,
  useOpenDirectory,
  useSeedFirstHome,
  useSeedStarter,
} from "@/hooks/useFinishPendingStart";
import { useLegalIndex } from "@/hooks/useLegalDocuments";
import { useServer } from "@/hooks/useServer";
import { useWizard } from "@/hooks/useWizard";
import { EMPTY_PLACE, nearOfPlace } from "@/lib/directoryNear";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { returnPath } from "@/lib/returnPath";
import {
  clearStart,
  findStartedCommunity,
  freshAnswers,
  newCommunity,
  readStartDraft,
  type StartAnswers,
  type StartPath,
  savePendingStart,
  saveStartDraft,
} from "@/lib/startFlow";
import { Button } from "@/ui/button";
import { Card } from "@/ui/card";
import { WizardFrame } from "@/ui/wizard-dialog";

type Step =
  | "choose"
  | "invite"
  | "interest"
  | "you"
  | "personal"
  | "shared"
  | "plan"
  | "account"
  | "codes"
  | "finishing"
  | "people"
  | "checkEmail"
  | "underAge";

const PATH_ORDER: StartPath[] = ["invite", "join", "personal", "shared"];

/** The last part of a pasted invite link, or the code as typed. */
const inviteCodeFrom = (text: string): string =>
  text.trim().split(/[?#]/)[0].split("/").filter(Boolean).pop() ?? "";

export interface StartFlowProps {
  /** Signed in already: the flow makes a community rather than an account. */
  signedIn?: boolean;
  /** From the URL: go straight to the invited path. */
  inviteCode?: string;
  /** Signed in: true while a community is being made and set up, so the
   *  layout keeps the flow on screen once the account has one. */
  onBusy?: (busy: boolean) => void;
  /** Under the steps, inside the card. */
  footer?: ReactNode;
  /** Where to land once the account is made, in place of where the flow would:
   *  the page that sent somebody to sign up, such as a plug-in's sign-in. */
  next?: string;
}

/** Waits for what decides which paths are offered, then starts the steps. */
export const StartFlow = (props: StartFlowProps) => {
  const { signedIn = false } = props;
  const { isLoading, communityDirectoryEnabled } = useAppConfig();
  // Whether a plan step is offered waits on a phone's store, so the steps are
  // not laid out before it is known.
  const { isLoading: sellingLoading } = useBillingPortal();
  const { canCreateCommunities } = useCommunities();
  const bootstrap = useBootstrapStatus({
    query: { enabled: !signedIn, retry: false },
  });

  if (isLoading || sellingLoading || (!signedIn && bootstrap.isPending)) {
    return (
      <SignInFrame>
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </SignInFrame>
    );
  }

  // Signing up without an invite needs public registration (which the server
  // reports closed when communities cannot be made either). Signed in, making
  // a community needs that account to be allowed to.
  const registrationOpen = signedIn || bootstrap.data?.public_registration_enabled !== false;
  const paths = PATH_ORDER.filter((path) => {
    if (path === "invite") return true;
    if (!registrationOpen) return false;
    if (path === "join") return communityDirectoryEnabled;
    return !signedIn || canCreateCommunities;
  });
  return <StartSteps {...props} signedIn={signedIn} paths={paths} />;
};

const StartSteps = ({
  signedIn,
  inviteCode: urlCode,
  onBusy,
  footer,
  next: nextParam,
  paths,
}: StartFlowProps & { signedIn: boolean; paths: StartPath[] }) => {
  const { t } = useTranslation(["auth", "common", "communities"]);
  const navigate = useNavigate();
  const { user } = useAuth();
  const signUp = useSignUp();
  const { communities, loading: communitiesLoading, createCommunity } = useCommunities();
  const { captcha, communityAgeGateEnabled } = useAppConfig();
  const { getServerOrigin } = useServer();
  const { billing, canSell, openPortal, reserveTab } = useBillingPortal();
  // A plan is picked only where it can be bought. Where this device may not
  // sell (a phone app outside the store countries that allow it), the flow has
  // no plan step: the community starts on the free plan, and
  // the welcome letter is the way to the rest.
  const plansShown = canSell;
  const catalog = useBillingCatalog(plansShown ? billing?.url : null);
  const seed = useSeedStarter();
  const landOn = useLandOnStarter();
  const seedHome = useSeedFirstHome();
  const openDirectory = useOpenDirectory();

  const [answers, setAnswers] = useState<StartAnswers>(() => {
    const draft = readStartDraft();
    if (urlCode)
      return { ...(draft ?? freshAnswers("invite")), path: "invite", inviteCode: urlCode };
    if (draft && paths.includes(draft.path)) return draft;
    return freshAnswers(paths.includes("personal") ? "personal" : paths[0]);
  });
  // A reload or a trip to a password manager loses nothing.
  useEffect(() => saveStartDraft(answers), [answers]);
  const update = (patch: Partial<StartAnswers>) => setAnswers((prev) => ({ ...prev, ...patch }));

  // Held in memory only: the server keeps whether it was answered, never the date.
  const age = useAgeConfirmation(() => commit("finishing"));
  const ageAnswered = Boolean(user?.age_confirmed_at || user?.age_below_minimum_at);
  const asksAge = communityAgeGateEnabled && !(signedIn && ageAnswered);
  // Joining a listed community needs the answer; anywhere else it can wait.
  const ageRequired = asksAge && answers.path === "join";

  // Every name has an answer before anybody types one, starting from the handle.
  const handle = (signedIn ? (user?.username ?? "") : answers.username).trim();
  const withDefaults = (a: StartAnswers): StartAnswers => {
    if (a.path !== "personal" && a.path !== "shared") return a;
    const group = a.path;
    return {
      ...a,
      communityName:
        a.communityName.trim() ||
        (handle
          ? t(`start.${group}.nameDefault`, { name: handle })
          : t(`start.${group}.nameFallback`)),
      initiativeName: a.initiativeName.trim() || t(`start.${group}.initiativeDefault`),
      listName: a.listName.trim() || (group === "personal" ? t("start.personal.listDefault") : ""),
    };
  };

  const tiers = (catalog.data?.tiers ?? []).filter(
    (tier) => tier.kind === "free_hosted" || tier.kind === "paid"
  );
  const entryTier = tiers.find((tier) => tier.kind === "free_hosted") ?? tiers[0];
  const chosenTier = tiers.find((tier) => tier.id === answers.planId) ?? entryTier;
  const wantsPlan =
    plansShown && answers.path === "shared" && Boolean(chosenTier) && chosenTier !== entryTier;
  // Opened inside the click that makes the account or community, so the
  // browser lets it through; pointed at the portal once there is a session.
  const pickedPlan = wantsPlan ? chosenTier?.id : undefined;
  const planTab = useRef<Window | null>(null);
  const reservePlanTab = () => {
    planTab.current?.close();
    planTab.current = wantsPlan ? reserveTab() : null;
  };
  const dropPlanTab = () => {
    planTab.current?.close();
    planTab.current = null;
  };

  const sequence = (path: StartPath): Step[] => {
    const you: Step[] = signedIn ? [] : ["you"];
    const account: Step[] = signedIn ? [] : ["account"];
    switch (path) {
      case "invite":
        return ["invite", ...you, ...account];
      case "join":
        return ["interest", ...(asksAge || !signedIn ? (["you"] as Step[]) : []), ...account];
      case "personal":
        return [...you, "personal", ...account];
      case "shared":
        return [...you, "shared", ...(plansShown ? (["plan"] as Step[]) : []), ...account];
    }
  };
  const flow: Step[] = [
    ...(paths.length > 1 && !urlCode ? (["choose"] as Step[]) : []),
    ...sequence(answers.path),
  ];
  const { step, go, back, commit, canGoBack, reset } = useWizard<Step>(flow[0]);
  const position = flow.indexOf(step);
  // An under-age answer is recorded and refused; the refreshed account says so.
  useEffect(() => {
    if (signedIn && step === "you" && user?.age_below_minimum_at) commit("underAge");
  }, [signedIn, step, user?.age_below_minimum_at, commit]);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // -- invite --------------------------------------------------------------
  const [invite, setInvite] = useState<{
    code: string;
    status: CommunityInviteStatus | null;
    error: string | null;
    checking: boolean;
  }>({ code: "", status: null, error: null, checking: false });
  const checkInvite = async (code: string): Promise<boolean> => {
    setInvite({ code, status: null, error: null, checking: true });
    try {
      const status = await getInviteStatus(encodeURIComponent(code));
      setInvite({
        code,
        status,
        error: status.is_valid ? null : (status.reason ?? t("register.inviteNoLongerValid")),
        checking: false,
      });
      return status.is_valid;
    } catch {
      setInvite({ code, status: null, error: t("register.unableToLoadInvite"), checking: false });
      return false;
    }
  };
  // A code from the URL is checked as soon as the step shows it.
  const checkedUrlCode = useRef(false);
  useEffect(() => {
    if (checkedUrlCode.current || !urlCode || signedIn) return;
    checkedUrlCode.current = true;
    void checkInvite(inviteCodeFrom(urlCode));
  });

  // -- moving on -----------------------------------------------------------
  const next = () => {
    setError(null);
    const to = flow[position + 1];
    if (!to) {
      void finishSignedIn();
      return;
    }
    if (to === "personal" || to === "shared") setAnswers(withDefaults);
    go(to);
  };

  const choosePath = (path: StartPath) =>
    setAnswers((prev) =>
      prev.path === path
        ? prev
        : {
            ...freshAnswers(path, prev.inviteCode),
            username: prev.username,
            timezone: prev.timezone,
          }
    );

  const continueInvite = async () => {
    const code = inviteCodeFrom(answers.inviteCode);
    if (!code) return;
    if (signedIn) {
      await navigate({ to: "/invite/$code", params: { code } });
      return;
    }
    if ((invite.code === code && invite.status?.is_valid) || (await checkInvite(code))) next();
  };

  /** Signed in: the last question answered, so make what it asked for. */
  const madeCommunity = useRef<CommunityRead | null>(null);
  const finishSignedIn = async () => {
    if (answers.path === "join") {
      if (asksAge) await age.confirm();
      else commit("finishing");
      return;
    }
    const final = withDefaults(answers);
    setBusy(true);
    reservePlanTab();
    onBusy?.(true);
    try {
      madeCommunity.current = await createCommunity({
        name: final.communityName.trim(),
        description: final.description.trim() || undefined,
      });
      commit("finishing");
    } catch (err) {
      dropPlanTab();
      onBusy?.(false);
      setError(getErrorMessage(err, "communities:unableToCreateCommunity"));
    } finally {
      setBusy(false);
    }
  };

  // -- once signed in ------------------------------------------------------
  const [made, setMade] = useState<{ id: number; name: string } | null>(null);
  // A plan was picked but no tab could be held open for it: offered as a
  // button instead, which is a click of its own.
  const [planByButton, setPlanByButton] = useState(false);
  const finishing = useRef(false);
  // The page that sent somebody here, when one did, is where every ending lands.
  const resumeTo = returnPath(nextParam);
  const leave = async (to: () => Promise<unknown>) => {
    await (resumeTo ? navigate({ href: resumeTo }) : to());
    onBusy?.(false);
  };
  useEffect(() => {
    if (step !== "finishing" || finishing.current || !user || communitiesLoading) return;
    finishing.current = true;
    const final = withDefaults(answers);
    void (async () => {
      await clearStart();
      if (final.path === "join") {
        seedHome("join");
        if (user.age_below_minimum_at) commit("underAge");
        else await leave(() => openDirectory(final.categories, nearOfPlace(final.near)));
        return;
      }
      if (final.path === "invite") {
        const communityId = invite.status?.community_id;
        seedHome("invite", { communityId });
        await leave(() =>
          communityId
            ? navigate({ to: "/c/$communityId", params: { communityId: String(communityId) } })
            : navigate({ to: "/" })
        );
        return;
      }
      const community = madeCommunity.current ?? findStartedCommunity(communities, final);
      if (!community) {
        dropPlanTab();
        await leave(() => navigate({ to: "/" }));
        return;
      }
      const starter = await seed(community.id, final);
      seedHome(final.path, firstHomeContext(community.id, starter));
      if (final.path === "personal") {
        await leave(() => landOn(community.id, starter));
        return;
      }
      if (planTab.current) {
        toast.info(t("communities:billingSetup.opening", { community: community.name }));
        void openPortal(community.id, "upgrade", planTab.current, { plan: pickedPlan });
        planTab.current = null;
      } else if (wantsPlan) {
        setPlanByButton(true);
      }
      setMade({ id: community.id, name: community.name });
      commit("people");
    })();
  });

  // -- account -------------------------------------------------------------
  const [email, setEmail] = useState("");
  const [emailDoor, setEmailDoor] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [held, setHeld] = useState<{ approval: boolean; underAge: boolean } | null>(null);
  const inviteParam = answers.path === "invite" ? inviteCodeFrom(answers.inviteCode) : undefined;
  const inviteBlocked = answers.path === "invite" && !invite.status?.is_valid;

  // The signed number the name check showed, so the account gets it.
  const [handleOffer, setHandleOffer] = useState<string | null>(null);
  // The documents the form's notice showed, which the registration records.
  const legal = useLegalIndex();
  const signUpDetails = (captchaToken = "") => {
    const final = withDefaults(answers);
    return {
      email: email.toLowerCase().trim(),
      username: final.username.trim().toLowerCase(),
      timezone: final.timezone,
      captcha_token: captcha ? captchaToken : undefined,
      community: newCommunity(final),
      birthdate: age.birthdate || undefined,
      username_offer: handleOffer ?? undefined,
      accepted_documents: legal.shownSlugs,
    };
  };

  const submitPassword = async (password: string, captchaToken: string) => {
    reservePlanTab();
    setBusy(true);
    setError(null);
    const details = signUpDetails(captchaToken);
    try {
      const { made: created, signedIn } = await signUp.withPassword(details, password, inviteParam);
      if (signedIn) {
        commit("finishing");
        return;
      }
      // Made, but it cannot sign in yet: the rest waits for its first sign-in
      // on this browser.
      dropPlanTab();
      const underAge = Boolean(created.age_below_minimum_at);
      await clearStart();
      // Left for the first sign-in when there is something to finish, or a
      // page that sent them here to return to.
      if (resumeTo || (answers.path !== "invite" && !(answers.path === "join" && underAge))) {
        await savePendingStart(details.email, withDefaults(answers), resumeTo);
      }
      setHeld({ approval: created.status !== "active", underAge });
      commit("checkEmail");
    } catch (err) {
      dropPlanTab();
      setError(signUp.failure(err));
    } finally {
      setBusy(false);
    }
  };

  const submitPasskey = async (captchaToken: string) => {
    reservePlanTab();
    setBusy(true);
    setError(null);
    try {
      await signUp.withPasskey(signUpDetails(captchaToken), inviteParam, (codes) => {
        setRecoveryCodes(codes);
        commit("codes");
      });
    } catch (err) {
      dropPlanTab();
      setError(signUp.failure(err, true));
    } finally {
      setBusy(false);
    }
  };

  // The emailed-code card takes the whole frame while it is open, as it does
  // on the sign-in page.
  if (emailDoor) {
    const { username, timezone, community, birthdate, username_offer } = signUpDetails();
    return (
      <SignInFrame fillPhone>
        <EmailOtpCard
          inviteCode={inviteParam}
          registration={{ username, timezone, community, birthdate, username_offer }}
          onCancel={() => setEmailDoor(false)}
          onSignedIn={(registered) => {
            setEmailDoor(false);
            if (registered) {
              commit("finishing");
              return;
            }
            // The address already had an account, so nothing was made: on to
            // the invite, or home.
            void clearStart();
            void leave(() =>
              inviteParam
                ? navigate({ to: "/invite/$code", params: { code: inviteParam } })
                : navigate({ to: "/" })
            );
          }}
        />
      </SignInFrame>
    );
  }

  // -- the steps -----------------------------------------------------------
  const inviteLine = invite.checking
    ? t("register.checkingInvite")
    : invite.status?.is_valid
      ? invite.status.community_name
        ? t("register.joiningCommunity", { communityName: invite.status.community_name })
        : t("register.joiningCommunityDefault")
      : null;

  let title: string;
  let pose: YonderPose;
  let line: string | null = null;
  let body: ReactNode;
  switch (step) {
    case "choose":
      title = t("start.choose.title");
      pose = "talking";
      line = t("start.choose.description");
      body = (
        <ChooseStep
          paths={paths}
          value={answers.path}
          onChange={choosePath}
          onContinue={next}
          disabled={busy}
        />
      );
      break;

    case "invite": {
      // Signing up by invite only: say so, in the words the closed sign-up
      // page always used.
      const inviteOnly = !signedIn && paths.length === 1;
      title = t(inviteOnly ? "inviteRequired.title" : "start.invite.title");
      pose = "talking";
      line = t(inviteOnly ? "inviteRequired.subtitle" : "start.invite.description");
      body = (
        <InviteStep
          code={answers.inviteCode}
          onCodeChange={(inviteCode) => update({ inviteCode })}
          status={inviteLine}
          error={invite.error}
          checking={invite.checking}
          canContinue={Boolean(inviteCodeFrom(answers.inviteCode))}
          onSubmit={() => void continueInvite()}
        />
      );
      break;
    }

    case "interest":
      title = t("start.interest.title");
      pose = "thinking";
      line = t("start.interest.description");
      body = (
        <InterestStep
          value={answers.categories}
          onChange={(categories) => update({ categories })}
          near={answers.near}
          onNearChange={(near) => update({ near })}
          onContinue={next}
          onSkip={() => {
            update({ categories: [], near: EMPTY_PLACE });
            next();
          }}
          disabled={busy}
        />
      );
      break;

    case "you":
      if (signedIn) {
        // Signed in, this step is only ever the age question for joining.
        title = t("confirmAge.title");
        pose = "thinking";
        line = t("communities:community.ageGateBody");
      } else {
        title = t("start.you.title");
        pose = "talking";
        line = inviteLine ?? t("start.you.description");
      }
      body = (
        <YouStep
          signedIn={signedIn}
          username={answers.username}
          onUsernameChange={(username) => update({ username })}
          onHandleOffer={setHandleOffer}
          timezone={answers.timezone}
          onTimezoneChange={(timezone) => update({ timezone })}
          age={age}
          asksAge={asksAge}
          ageRequired={ageRequired}
          busy={busy}
          onContinue={next}
        />
      );
      break;

    case "personal":
    case "shared":
      title = t(`start.${step}.title`);
      pose = "winking";
      line = t(`start.${step}.description`);
      body = (
        <CommunityStep
          path={step}
          answers={answers}
          update={update}
          onContinue={next}
          disabled={busy}
        />
      );
      break;

    case "plan":
      title = t("start.plan.title");
      pose = "winking";
      line = t("start.plan.description");
      body = (
        <PlanStep
          tiers={tiers}
          entry={entryTier}
          chosen={chosenTier}
          loading={catalog.isPending}
          onPick={(planId) => update({ planId })}
          onContinue={next}
          onSkip={() => {
            update({ planId: entryTier?.id ?? null });
            next();
          }}
          disabled={busy}
        />
      );
      break;

    case "account":
      title = t("start.account.title");
      pose = "talking";
      line = inviteLine ?? t("start.account.description");
      body = (
        <AccountStep
          email={email}
          onEmailChange={setEmail}
          busy={busy}
          blocked={inviteBlocked}
          onPassword={submitPassword}
          onPasskey={submitPasskey}
          onEmailCode={() => setEmailDoor(true)}
          onError={setError}
        />
      );
      break;

    case "codes":
      title = t("start.account.title");
      pose = "proud";
      body = (
        <RecoveryCodesPanel
          codes={recoveryCodes}
          note={t("register.recoveryCodesNote")}
          onDone={() => commit("finishing")}
        />
      );
      break;

    case "finishing":
      title = t("start.finishing");
      pose = "excited";
      body = <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />;
      break;

    case "checkEmail":
      title = held?.approval ? t("start.checkEmail.approvalTitle") : t("start.checkEmail.title");
      pose = "farewell";
      line = held?.approval
        ? t("start.checkEmail.approvalDescription")
        : t("start.checkEmail.description", { email: email.trim() });
      body = (
        <>
          {held?.underAge ? <p className="text-sm">{t("start.underAge")}</p> : null}
          {wantsPlan ? <p className="text-sm">{t("start.checkEmail.planLater")}</p> : null}
          <Button asChild className="w-full">
            <Link to="/login">{t("start.checkEmail.signIn")}</Link>
          </Button>
        </>
      );
      break;

    case "underAge":
      title = t("confirmAge.blockedTitle");
      pose = "idle";
      line = t("start.underAge");
      body = (
        <ContinueButton
          onClick={() => {
            if (signedIn) reset();
            else void navigate({ to: "/" });
          }}
        />
      );
      break;

    case "people":
      title = t("start.people.title");
      pose = "proud";
      line = t("start.people.description", {
        community: made?.name ?? withDefaults(answers).communityName,
      });
      body = made ? (
        <>
          <PeopleStep
            communityId={made.id}
            origin={getServerOrigin() ?? window.location.origin}
            planButton={
              planByButton
                ? () => void openPortal(made.id, "upgrade", null, { plan: pickedPlan })
                : undefined
            }
            onDone={() => void leave(() => landOn(made.id, null))}
            doneLabel={t("start.people.goToCommunity", { community: made.name })}
          />
        </>
      ) : null;
      break;
  }

  return (
    <SignInFrame fillPhone>
      <Card className="grid w-full max-w-lg gap-4 p-6 shadow-lg max-sm:min-h-dvh max-sm:max-w-none max-sm:content-start max-sm:rounded-none max-sm:border-0 max-sm:pt-[max(1.5rem,env(safe-area-inset-top))] max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <YonderSays key={step} pose={pose} line={line} />
        <WizardFrame
          title={title}
          progress={
            position >= 0 && flow.length > 1
              ? { current: position + 1, total: flow.length }
              : undefined
          }
          onBack={canGoBack && !busy ? back : undefined}
          backLabel={t("common:back")}
        >
          {body}
          {error ? (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          ) : null}
          {footer}
        </WizardFrame>
        {signedIn ? <ServerChip /> : <ServerPicker />}
      </Card>
    </SignInFrame>
  );
};

/**
 * Everything an operator does to one account, in one place.
 *
 * The users table had grown a column per decision — a name, a role dropdown —
 * and a dropdown menu for the rest, which put the account's handle and the
 * levers that act on it in different places. The community table had already
 * solved this: the row identifies, the sheet decides.
 *
 * Each control saves on its own, the way the cells did, because each is a
 * separate endpoint with its own capability behind it.
 *
 * Every control is drawn from the row's `allowed_actions`, which the server
 * works out for this viewer and this account — their capabilities, their rung,
 * and the account's state — so each viewer is offered what they may do here
 * and nothing else.
 */

import { Link } from "@tanstack/react-router";
import {
  CalendarClock,
  Eraser,
  ImageOff,
  KeyRound,
  LockOpen,
  LogOut,
  Mail,
  MailCheck,
  ShieldOff,
  Trash2,
  UserCheck,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type OperatorUserRead,
  UserAction,
  type UserRole,
} from "@/api/generated/initiativeAPI.schemas";
import { CasePicker } from "@/components/platform/CasePicker";
import { OperatorDeleteUserDialog } from "@/components/platform/OperatorDeleteUserDialog";
import { Section, SettingRow } from "@/components/platform/SettingRow";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useGrantCases } from "@/hooks/useAccessGrants";
import { useAuth } from "@/hooks/useAuth";
import {
  type OperatorProfileField,
  useOperatorAccountCases,
  useOperatorClearAgeBlock,
  useOperatorClearProfileField,
  useOperatorClearSecondFactor,
  useOperatorLiftSignInLock,
  useOperatorReactivateUser,
  useOperatorRemoveAvatar,
  useOperatorResendVerification,
  useOperatorRestoreUser,
  useOperatorRevokeApiKeys,
  useOperatorSetSuspension,
  useOperatorSetUsername,
  useOperatorSignOutEverywhere,
  useOperatorTriggerPasswordReset,
  useOperatorUpdatePlatformRole,
} from "@/hooks/useOperatorUsers";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasAnyCapability } from "@/lib/permissions";
import { getUserHandle } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/ui/sheet";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

/** Platform roles ordered least → most privileged. */
export const PLATFORM_ROLE_ORDER: UserRole[] = [
  "member",
  "moderator",
  "support",
  "operator",
  "owner",
];

export const platformRoleRank = (role: UserRole): number => PLATFORM_ROLE_ORDER.indexOf(role);

const platformRoleLabel = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roles.${role}`);

const platformRoleDescription = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roleDescriptions.${role}`);

/** True when the sheet would offer something for this account: any action on
 *  it, or its open cases. Every act on an account is taken here, where the
 *  case it is for can be named. */
export const sheetOffersSomething = (target: OperatorUserRead): boolean =>
  target.open_case_count > 0 || target.allowed_actions.length > 0;

/** The three parts of a profile a moderator clears, each with the action that
 *  allows it and where its words live. */
const PROFILE_FIELDS: {
  field: OperatorProfileField;
  action: UserAction;
  key: "displayNames" | "customStatus" | "decorations";
}[] = [
  { field: "display_names", action: UserAction.clear_display_names, key: "displayNames" },
  { field: "custom_status", action: UserAction.clear_custom_status, key: "customStatus" },
  { field: "decorations", action: UserAction.clear_decorations, key: "decorations" },
];

/**
 * The open cases an account filed or is the subject of, read only once the
 * sheet is open. Each links to its task; the list carries no title, since
 * what a case says is for whoever may open it.
 */
const AccountCases = ({ user, open }: { user: OperatorUserRead; open: boolean }) => {
  const { t } = useTranslation(["settings", "intake"]);
  const cases = useOperatorAccountCases(user.id, {
    enabled: open && user.open_case_count > 0,
  });

  return (
    <Section title={t("platformUsers.sheet.cases.title")}>
      <div className="space-y-3 py-3">
        <p className="text-sm">
          {t("platformUsers.sheet.cases.count", { count: user.open_case_count })}
        </p>
        {cases.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("platformUsers.sheet.cases.loading")}</p>
        ) : cases.isError ? (
          <p className="text-destructive text-sm">{t("platformUsers.sheet.cases.loadError")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {(cases.data ?? []).map((item) => (
              <li key={item.task_id}>
                <Link
                  to="/c/$communityId/i/$initiativeId/projects/$projectId/tasks/$taskId"
                  params={{
                    communityId: String(item.community_id),
                    initiativeId: String(item.initiative_id),
                    projectId: String(item.project_id),
                    taskId: String(item.task_id),
                  }}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-muted focus-visible:bg-muted"
                >
                  <span className="min-w-0 truncate">
                    {t(`intake:streams.${item.stream}.title`)} ·{" "}
                    {item.filed
                      ? t("platformUsers.sheet.cases.filed")
                      : t("platformUsers.sheet.cases.about")}
                  </span>
                  <span className="shrink-0 font-mono text-muted-foreground text-xs">
                    #{item.task_id}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground text-xs">{t("platformUsers.sheet.cases.help")}</p>
      </div>
    </Section>
  );
};

export const UserOperatorSettingsSheet = ({
  user,
  open,
  onOpenChange,
  actorRole,
}: {
  user: OperatorUserRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The viewer's own rung: no role above it is offered. */
  actorRole: UserRole;
}) => {
  const { t } = useTranslation(["settings", "common"]);

  // The draft follows whichever account the sheet was opened for.
  const form = useServerForm(
    user ?? undefined,
    (loaded) => ({ username: loaded?.username ?? "" }),
    [open, user?.id]
  );
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [suspendReason, setSuspendReason] = useState("");
  const [roleConfirm, setRoleConfirm] = useState<UserRole | null>(null);
  const [avatarConfirm, setAvatarConfirm] = useState(false);
  const [apiKeysConfirm, setApiKeysConfirm] = useState(false);
  const [signOutConfirm, setSignOutConfirm] = useState(false);
  const [clearing, setClearing] = useState<OperatorProfileField | null>(null);
  const [resetConfirm, setResetConfirm] = useState(false);
  const [secondFactorConfirm, setSecondFactorConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // The acts here may be taken for an operations case, which hears of each.
  // Chosen afresh for each account the sheet opens on.
  const { user: viewer } = useAuth();
  const mayNameCase = hasAnyCapability(viewer, [Capability.accessRequest, Capability.dataBypass]);
  const grantCases = useGrantCases({ enabled: open && mayNameCase });
  const [caseTaskId, setCaseTaskId] = useState<number | null>(null);
  // A new account starts with no case.
  const [prevUserId, setPrevUserId] = useState(user?.id);
  if (prevUserId !== user?.id) {
    setPrevUserId(user?.id);
    setCaseTaskId(null);
  }

  const setUsername = useOperatorSetUsername(
    {
      onSuccess: () => toast.success(t("platformUsers.usernameChanged")),
      onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
    },
    caseTaskId
  );

  const setSuspension = useOperatorSetSuspension(
    {
      onSuccess: () => {
        setSuspendOpen(false);
        setSuspendReason("");
      },
      onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
    },
    caseTaskId
  );

  const updateRole = useOperatorUpdatePlatformRole(
    {
      onSuccess: (_data, variables) => {
        toast.success(
          t("platformUsers.roleChangeSuccess", {
            role: platformRoleLabel(variables.role, t as TranslateFn),
          })
        );
        setRoleConfirm(null);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.roleChangeError"));
        setRoleConfirm(null);
      },
    },
    caseTaskId
  );

  const removeAvatar = useOperatorRemoveAvatar(
    {
      onSuccess: () => {
        toast.success(t("platformUsers.sheet.avatarRemoved"));
        setAvatarConfirm(false);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
        setAvatarConfirm(false);
      },
    },
    caseTaskId
  );

  const revokeApiKeys = useOperatorRevokeApiKeys(
    {
      onSuccess: () => {
        toast.success(t("platformUsers.sheet.apiKeysRevoked"));
        setApiKeysConfirm(false);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
        setApiKeysConfirm(false);
      },
    },
    caseTaskId
  );

  const signOut = useOperatorSignOutEverywhere(
    {
      onSuccess: () => {
        toast.success(t("platformUsers.sheet.signOutDone"));
        setSignOutConfirm(false);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
        setSignOutConfirm(false);
      },
    },
    caseTaskId
  );

  const clearField = useOperatorClearProfileField(
    {
      onSuccess: (_data, variables) => {
        const entry = PROFILE_FIELDS.find((item) => item.field === variables.field);
        if (entry) toast.success(t(`platformUsers.sheet.clear.${entry.key}.done`));
        setClearing(null);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
        setClearing(null);
      },
    },
    caseTaskId
  );

  const actionError = (err: unknown) =>
    toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
  const handle = user ? getUserHandle(user) : "";

  const resetPassword = useOperatorTriggerPasswordReset(
    {
      onSuccess: () => {
        toast.success(t("platformUsers.resetSuccess", { handle }));
        setResetConfirm(false);
      },
      onError: (err) => {
        toast.error(getErrorMessage(err, "settings:platformUsers.resetError"));
        setResetConfirm(false);
      },
    },
    caseTaskId
  );
  // Sends nothing new and changes nothing, so no case hears of it.
  const resendVerification = useOperatorResendVerification({
    onSuccess: () => toast.success(t("platformUsers.resendVerificationSuccess", { handle })),
    onError: (err) =>
      toast.error(getErrorMessage(err, "settings:platformUsers.resendVerificationError")),
  });
  const liftSignInLock = useOperatorLiftSignInLock(
    {
      onSuccess: () => toast.success(t("platformUsers.signInLockLifted")),
      onError: actionError,
    },
    caseTaskId
  );
  const clearSecondFactor = useOperatorClearSecondFactor(
    {
      onSuccess: () => {
        toast.success(t("platformUsers.secondFactorCleared"));
        setSecondFactorConfirm(false);
      },
      onError: (err) => {
        actionError(err);
        setSecondFactorConfirm(false);
      },
    },
    caseTaskId
  );
  const clearAgeBlock = useOperatorClearAgeBlock(
    {
      onSuccess: () => toast.success(t("platformUsers.ageBlockCleared")),
      onError: actionError,
    },
    caseTaskId
  );
  const reactivate = useOperatorReactivateUser(
    {
      onSuccess: () => toast.success(t("platformUsers.reactivateSuccess", { handle })),
      onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.reactivateError")),
    },
    caseTaskId
  );
  const restore = useOperatorRestoreUser(
    {
      onSuccess: () => toast.success(t("platformUsers.restoreSuccess", { handle })),
      onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.restoreError")),
    },
    caseTaskId
  );

  if (!user) return null;

  const isSuspended = user.status === "suspended";
  const allows = (action: UserAction): boolean => user.allowed_actions.includes(action);

  // Each control is one of the row's `allowed_actions`: the server has already
  // asked the viewer's capability, their rung and the account's state.
  const showIdentity = allows(UserAction.rename);
  const showAvatar = allows(UserAction.remove_avatar);
  const clearable = PROFILE_FIELDS.filter((item) => allows(item.action));
  const showSuspension = allows(UserAction.suspend) || allows(UserAction.unsuspend);
  const showApiKeys = allows(UserAction.revoke_api_keys);
  const showSignOut = allows(UserAction.sign_out_everywhere);
  const showRole = allows(UserAction.change_role);
  const showReset = allows(UserAction.reset_password);
  const showResend = allows(UserAction.resend_verification);
  const showSignInLock = allows(UserAction.lift_sign_in_lock);
  const showSecondFactor = allows(UserAction.clear_second_factor);
  const showSignIn = showReset || showResend || showSignInLock || showSecondFactor;
  const showReactivate = allows(UserAction.reactivate);
  const showRestore = allows(UserAction.restore);
  const showAgeBlock = allows(UserAction.clear_age_block);
  const showStanding = showReactivate || showRestore || showAgeBlock;
  const showDelete = allows(UserAction.delete);
  const clearingEntry = PROFILE_FIELDS.find((item) => item.field === clearing) ?? null;

  const commitUsername = () => {
    const sent = form.values;
    const next = sent.username.trim().toLowerCase();
    if (!next || next === user.username) {
      form.reset(sent);
      return;
    }
    // A refused name goes back to the stored one.
    setUsername.mutate(
      { userId: user.id, username: next },
      { onSuccess: () => form.settle(sent), onError: () => form.reset(sent) }
    );
  };

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{getUserHandle(user)}</SheetTitle>
            <SheetDescription>{t("platformUsers.sheet.description")}</SheetDescription>
          </SheetHeader>

          {mayNameCase && (grantCases.data?.items.length ?? 0) > 0 ? (
            <div className="space-y-1 pt-4">
              <Label htmlFor="operator-user-case">{t("platformUsers.sheet.forCase")}</Label>
              <CasePicker
                cases={grantCases.data?.items ?? []}
                value={caseTaskId}
                onChange={setCaseTaskId}
                optional
                loading={grantCases.isLoading}
                aria-label={t("platformUsers.sheet.forCase")}
              />
              <p className="text-muted-foreground text-xs">
                {t("platformUsers.sheet.forCaseHelp")}
              </p>
            </div>
          ) : null}

          <div className="space-y-6 py-6">
            {showStanding && (
              <Section title={t("platformUsers.sheet.standing")}>
                {showReactivate && (
                  <SettingRow
                    label={t("platformUsers.sheet.reactivateLabel")}
                    help={t("platformUsers.sheet.reactivateHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => reactivate.mutate(user.id)}
                        disabled={reactivate.isPending}
                      >
                        <UserCheck className="h-4 w-4" />
                        {t("platformUsers.reactivate")}
                      </Button>
                    }
                  />
                )}
                {/* Distinct from reactivating: nothing was dropped, so this
                    puts the account back exactly where it was. */}
                {showRestore && (
                  <SettingRow
                    label={t("platformUsers.sheet.restoreLabel")}
                    help={t("platformUsers.sheet.restoreHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => restore.mutate(user.id)}
                        disabled={restore.isPending}
                      >
                        <UserCheck className="h-4 w-4" />
                        {t("platformUsers.restore")}
                      </Button>
                    }
                  />
                )}
                {showAgeBlock && (
                  <SettingRow
                    label={t("platformUsers.sheet.ageBlockLabel")}
                    help={t("platformUsers.sheet.ageBlockHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => clearAgeBlock.mutate(user.id)}
                        disabled={clearAgeBlock.isPending}
                      >
                        <CalendarClock className="h-4 w-4" />
                        {t("platformUsers.clearAgeBlock")}
                      </Button>
                    }
                  />
                )}
              </Section>
            )}

            {(showIdentity || showAvatar || clearable.length > 0) && (
              <Section title={t("platformUsers.sheet.identity")}>
                {showIdentity && (
                  <SettingRow
                    label={t("platformUsers.sheet.usernameLabel")}
                    help={t("platformUsers.sheet.usernameHelp")}
                    htmlFor="operator-user-username"
                    control={
                      <Input
                        id="operator-user-username"
                        className="w-48"
                        value={form.values.username}
                        autoCapitalize="none"
                        onChange={(event) =>
                          form.set({ username: event.target.value.toLowerCase() })
                        }
                        onBlur={commitUsername}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                        }}
                        disabled={setUsername.isPending}
                      />
                    }
                  />
                )}
                {showAvatar && (
                  <SettingRow
                    label={t("platformUsers.sheet.avatarLabel")}
                    help={t("platformUsers.sheet.avatarHelp")}
                    control={
                      <div className="flex items-center gap-3">
                        {/* The picture itself, because deciding whether it
                            should go is looking at it. */}
                        <ProfileAvatar user={user} hidePresence className="size-10" />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setAvatarConfirm(true)}
                          disabled={removeAvatar.isPending}
                        >
                          <ImageOff className="h-4 w-4" />
                          {t("platformUsers.sheet.avatarRemove")}
                        </Button>
                      </div>
                    }
                  />
                )}
                {/* Like the picture: taken down for what breaches the terms
                    of use, and theirs to set again. */}
                {clearable.map((item) => (
                  <SettingRow
                    key={item.field}
                    label={t(`platformUsers.sheet.clear.${item.key}.label`)}
                    help={t(`platformUsers.sheet.clear.${item.key}.help`)}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setClearing(item.field)}
                        disabled={clearField.isPending}
                        aria-label={t(`platformUsers.sheet.clear.${item.key}.action`)}
                      >
                        <Eraser className="h-4 w-4" />
                        {t("platformUsers.sheet.clear.button")}
                      </Button>
                    }
                  />
                ))}
              </Section>
            )}

            {(showSuspension || showApiKeys || showSignOut) && (
              <Section title={t("platformUsers.sheet.access")}>
                {showSuspension && (
                  <SettingRow
                    label={t("platformUsers.sheet.suspendLabel")}
                    help={t("platformUsers.sheet.suspendHelp")}
                    htmlFor="operator-user-suspended"
                    control={
                      <Switch
                        id="operator-user-suspended"
                        checked={isSuspended}
                        onCheckedChange={(checked) => {
                          // Lifting takes no explanation; imposing does.
                          if (checked) setSuspendOpen(true);
                          else setSuspension.mutate({ userId: user.id, suspended: false });
                        }}
                        disabled={setSuspension.isPending}
                      />
                    }
                  />
                )}
                {showApiKeys && (
                  <SettingRow
                    label={t("platformUsers.sheet.apiKeysLabel")}
                    help={t("platformUsers.sheet.apiKeysHelp", { count: user.api_key_count })}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setApiKeysConfirm(true)}
                        disabled={revokeApiKeys.isPending}
                      >
                        <KeyRound className="h-4 w-4" />
                        {t("platformUsers.sheet.apiKeysRevoke")}
                      </Button>
                    }
                  />
                )}
                {showSignOut && (
                  <SettingRow
                    label={t("platformUsers.sheet.signOutLabel")}
                    help={t("platformUsers.sheet.signOutHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setSignOutConfirm(true)}
                        disabled={signOut.isPending}
                      >
                        <LogOut className="h-4 w-4" />
                        {t("platformUsers.sheet.signOut")}
                      </Button>
                    }
                  />
                )}
              </Section>
            )}

            {showSignIn && (
              <Section title={t("platformUsers.sheet.signIn")}>
                {showReset && (
                  <SettingRow
                    label={t("platformUsers.sheet.resetLabel")}
                    help={t("platformUsers.sheet.resetHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setResetConfirm(true)}
                        disabled={resetPassword.isPending}
                      >
                        <Mail className="h-4 w-4" />
                        {t("platformUsers.resetPassword")}
                      </Button>
                    }
                  />
                )}
                {showResend && (
                  <SettingRow
                    label={t("platformUsers.sheet.resendLabel")}
                    help={t("platformUsers.sheet.resendHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => resendVerification.mutate(user.id)}
                        disabled={resendVerification.isPending}
                      >
                        <MailCheck className="h-4 w-4" />
                        {t("platformUsers.sheet.resend")}
                      </Button>
                    }
                  />
                )}
                {showSignInLock && (
                  <SettingRow
                    label={t("platformUsers.sheet.signInLockLabel")}
                    help={t("platformUsers.sheet.signInLockHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => liftSignInLock.mutate(user.id)}
                        disabled={liftSignInLock.isPending}
                      >
                        <LockOpen className="h-4 w-4" />
                        {t("platformUsers.sheet.signInLockLift")}
                      </Button>
                    }
                  />
                )}
                {showSecondFactor && (
                  <SettingRow
                    label={t("platformUsers.sheet.secondFactorLabel")}
                    help={t("platformUsers.sheet.secondFactorHelp")}
                    control={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setSecondFactorConfirm(true)}
                        disabled={clearSecondFactor.isPending}
                      >
                        <ShieldOff className="h-4 w-4" />
                        {t("platformUsers.sheet.secondFactorClear")}
                      </Button>
                    }
                  />
                )}
              </Section>
            )}

            {showRole && (
              <Section title={t("platformUsers.sheet.role")}>
                <SettingRow
                  label={t("platformUsers.sheet.roleLabel")}
                  help={t("platformUsers.sheet.roleHelp")}
                  htmlFor="operator-user-role"
                  control={
                    <Select
                      value={user.role}
                      onValueChange={(value) => setRoleConfirm(value as UserRole)}
                      disabled={updateRole.isPending}
                    >
                      <SelectTrigger id="operator-user-role" className="h-8 w-[160px]">
                        {platformRoleLabel(user.role, t as TranslateFn)}
                      </SelectTrigger>
                      <SelectContent className="max-w-xs">
                        {PLATFORM_ROLE_ORDER.map((role) => (
                          <SelectItem
                            key={role}
                            value={role}
                            // You cannot mint a role above your own rung.
                            // Demoting the platform's last owner is refused
                            // by the server, which says so.
                            disabled={platformRoleRank(role) > platformRoleRank(actorRole)}
                          >
                            <div className="flex flex-col gap-0.5">
                              <span className="font-medium">
                                {platformRoleLabel(role, t as TranslateFn)}
                              </span>
                              <span className="text-muted-foreground text-xs leading-snug">
                                {platformRoleDescription(role, t as TranslateFn)}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  }
                />
              </Section>
            )}

            {user.open_case_count > 0 && <AccountCases user={user} open={open} />}

            {/* The one thing here that may not be undone, so it comes last. */}
            {showDelete && (
              <Section title={t("platformUsers.sheet.deleteSection")}>
                <SettingRow
                  label={t("platformUsers.deleteUser")}
                  help={t("platformUsers.sheet.deleteHelp")}
                  control={
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      onClick={() => setDeleting(true)}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t("platformUsers.sheet.delete")}
                    </Button>
                  }
                />
              </Section>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Suspending shows its reason to the person it is about, so it is a
          field rather than an internal note. */}
      <ConfirmDialog
        open={suspendOpen}
        onOpenChange={(next) => {
          setSuspendOpen(next);
          if (!next) setSuspendReason("");
        }}
        title={t("platformUsers.suspendTitle", { handle: getUserHandle(user) })}
        description={t("platformUsers.suspendBody")}
        confirmLabel={t("platformUsers.suspend")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={setSuspension.isPending}
        onConfirm={() =>
          setSuspension.mutate({
            userId: user.id,
            suspended: true,
            reason: suspendReason.trim() || undefined,
          })
        }
      >
        <div className="space-y-2">
          <Label htmlFor="operator-suspend-reason">{t("platformUsers.suspendReasonLabel")}</Label>
          <Textarea
            id="operator-suspend-reason"
            value={suspendReason}
            onChange={(event) => setSuspendReason(event.target.value)}
            rows={3}
          />
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={roleConfirm !== null}
        onOpenChange={(next) => !next && setRoleConfirm(null)}
        title={t("platformUsers.changeRoleTitle")}
        description={t("platformUsers.changeRoleDescription", {
          email: user.email,
          role: roleConfirm ? platformRoleLabel(roleConfirm, t as TranslateFn) : "",
        })}
        confirmLabel={t("common:confirm")}
        loadingLabel={t("common:submitting")}
        isLoading={updateRole.isPending}
        onConfirm={() => roleConfirm && updateRole.mutate({ userId: user.id, role: roleConfirm })}
      />

      <ConfirmDialog
        open={avatarConfirm}
        onOpenChange={setAvatarConfirm}
        title={t("platformUsers.sheet.avatarConfirmTitle")}
        description={t("platformUsers.sheet.avatarConfirmBody", {
          handle: getUserHandle(user),
        })}
        confirmLabel={t("platformUsers.sheet.avatarRemove")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={removeAvatar.isPending}
        onConfirm={() => removeAvatar.mutate(user.id)}
      />

      <ConfirmDialog
        open={apiKeysConfirm}
        onOpenChange={setApiKeysConfirm}
        title={t("platformUsers.sheet.apiKeysConfirmTitle")}
        description={t("platformUsers.sheet.apiKeysConfirmBody", {
          handle: getUserHandle(user),
          count: user.api_key_count,
        })}
        confirmLabel={t("platformUsers.sheet.apiKeysRevoke")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={revokeApiKeys.isPending}
        onConfirm={() => revokeApiKeys.mutate(user.id)}
      />

      <ConfirmDialog
        open={signOutConfirm}
        onOpenChange={setSignOutConfirm}
        title={t("platformUsers.sheet.signOutConfirmTitle")}
        description={t("platformUsers.sheet.signOutConfirmBody", {
          handle: getUserHandle(user),
        })}
        confirmLabel={t("platformUsers.sheet.signOut")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={signOut.isPending}
        onConfirm={() => signOut.mutate(user.id)}
      />

      <ConfirmDialog
        open={resetConfirm}
        onOpenChange={setResetConfirm}
        title={t("platformUsers.resetPassword")}
        description={t("platformUsers.resetDescription", { handle })}
        confirmLabel={t("common:send")}
        loadingLabel={t("common:submitting")}
        isLoading={resetPassword.isPending}
        onConfirm={() => resetPassword.mutate(user.id)}
      />

      <ConfirmDialog
        open={secondFactorConfirm}
        onOpenChange={setSecondFactorConfirm}
        title={t("platformUsers.clearSecondFactor")}
        description={t("platformUsers.clearSecondFactorDescription", { handle })}
        confirmLabel={t("platformUsers.clearSecondFactorConfirm")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={clearSecondFactor.isPending}
        onConfirm={() => clearSecondFactor.mutate(user.id)}
      />

      {deleting && (
        <OperatorDeleteUserDialog
          open={deleting}
          onOpenChange={setDeleting}
          onSuccess={() => onOpenChange(false)}
          targetUser={user}
          caseTaskId={caseTaskId}
        />
      )}

      <ConfirmDialog
        open={clearingEntry !== null}
        onOpenChange={(next) => !next && setClearing(null)}
        title={
          clearingEntry ? t(`platformUsers.sheet.clear.${clearingEntry.key}.confirmTitle`) : ""
        }
        description={
          clearingEntry
            ? t(`platformUsers.sheet.clear.${clearingEntry.key}.confirmBody`, {
                handle: getUserHandle(user),
              })
            : ""
        }
        confirmLabel={t("platformUsers.sheet.clear.button")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={clearField.isPending}
        onConfirm={() => clearing && clearField.mutate({ userId: user.id, field: clearing })}
      />
    </>
  );
};

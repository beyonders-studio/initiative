/**
 * Where the account is signed in: the devices, then the browsers.
 *
 * A device is the phone or desktop app, one row for each copy installed: its
 * sign-in with the message device collecting under it, or a message device with
 * no sign-in. A browser is its session. A browser names itself by what its user
 * agent says it is, and the app by the name it signed in with.
 *
 * A phone or desktop app, and a device with no sign-in, are removed: signed out
 * and their messages withdrawn. A browser is signed out, which withdraws its
 * messages too. The session doing the reading is marked rather than offered an
 * end: signing the current one out is what the sign-out button is, on every
 * page.
 */
import { Monitor, MonitorSmartphone, Smartphone, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import {
  ClientKind as Kind,
  type SignedInSessionInfo,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useEndSignedIn, useMySessions, useRevokeOtherSessions } from "@/hooks/useSecurity";
import { toast } from "@/lib/mascotToast";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/ui/alert-dialog";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";

const KIND_ICONS = {
  [Kind.mobile]: Smartphone,
  [Kind.desktop]: Monitor,
  [Kind.unknown]: MonitorSmartphone,
} as const;

/** When a session was last used, or when it began if it has not been since. */
const lastActiveAt = (session: SignedInSessionInfo) => session.last_used_at ?? session.started_at;

/** A device is removed; a browser is signed out. */
const isRemoved = (session: SignedInSessionInfo) => session.id === null || session.device;

const SignedInRow = ({
  session,
  busy,
  onEnd,
}: {
  session: SignedInSessionInfo;
  busy: boolean;
  onEnd: () => void;
}) => {
  const { t } = useTranslation("settings");
  const active = useRelativeTime(lastActiveAt(session));
  const Icon = KIND_ICONS[session.kind] ?? MonitorSmartphone;
  const detail = [
    session.id === null ? t("security.notSignedIn") : null,
    session.ip,
    t("security.activeAt", { when: active }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="flex flex-wrap items-center gap-2 font-medium">
            {session.label ?? t("security.unknownDevice")}
            {session.is_current ? (
              <Badge variant="secondary">
                {isRemoved(session) ? t("security.thisDevice") : t("security.thisBrowser")}
              </Badge>
            ) : null}
          </p>
          <p className="text-muted-foreground text-sm">{detail}</p>
        </div>
      </div>
      {session.is_current ? null : (
        <Button type="button" variant="outline" size="sm" onClick={onEnd} disabled={busy}>
          <Trash2 className="h-4 w-4" />
          {isRemoved(session) ? t("security.removeDevice") : t("security.signOut")}
        </Button>
      )}
    </div>
  );
};

export const SignedInSection = () => {
  const { t } = useTranslation("settings");
  const [pendingEnd, setPendingEnd] = useState<SignedInSessionInfo | null>(null);
  const [confirmSweep, setConfirmSweep] = useState(false);

  const sessionsQuery = useMySessions();

  const endSignedIn = useEndSignedIn({
    onSuccess: (_, row) =>
      toast.success(isRemoved(row) ? t("security.removedDevice") : t("security.signedOutOne")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setPendingEnd(null),
  });
  const revokeOthers = useRevokeOtherSessions({
    onSuccess: () => toast.success(t("security.signedOutOthers")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setConfirmSweep(false),
  });

  // The current session first, then the most recently active.
  const sessions = useMemo(
    () =>
      [...(sessionsQuery.data ?? [])].sort((a, b) => {
        if (a.is_current !== b.is_current) return a.is_current ? -1 : 1;
        return new Date(lastActiveAt(b)).getTime() - new Date(lastActiveAt(a)).getTime();
      }),
    [sessionsQuery.data]
  );

  const groups = [
    { heading: t("security.devicesHeading"), rows: sessions.filter(isRemoved) },
    {
      heading: t("security.browsersHeading"),
      rows: sessions.filter((session) => !isRemoved(session)),
    },
  ].filter((group) => group.rows.length > 0);
  const endable = sessions.filter((session) => session.id !== null && !session.is_current);
  const removing = pendingEnd !== null && isRemoved(pendingEnd);

  return (
    <SettingsSection
      title={t("security.signedInTitle")}
      description={t("security.signedInDescription")}
    >
      {sessionsQuery.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("security.loadingDevices")}</p>
      ) : sessionsQuery.isError ? (
        <p className="text-destructive text-sm">{t("security.devicesError")}</p>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-6 text-center text-muted-foreground">
          <MonitorSmartphone className="h-10 w-10 opacity-50" />
          <div>
            <p className="font-medium">{t("security.noSignedIn")}</p>
            <p className="text-sm">{t("security.noSignedInHint")}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.heading} className="space-y-3">
              <h3 className="font-medium text-muted-foreground text-sm">{group.heading}</h3>
              {group.rows.map((session) => (
                <SignedInRow
                  key={session.id ?? session.message_device_id}
                  session={session}
                  busy={endSignedIn.isPending}
                  onEnd={() => setPendingEnd(session)}
                />
              ))}
            </section>
          ))}

          {endable.length > 0 ? (
            <div className="flex justify-end pt-1">
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmSweep(true)}
                disabled={revokeOthers.isPending}
              >
                {t("security.signOutOthers")}
              </Button>
            </div>
          ) : null}
        </div>
      )}

      <AlertDialog open={pendingEnd !== null} onOpenChange={() => setPendingEnd(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {removing ? t("security.removeDeviceDialogTitle") : t("security.signOutDialogTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey={
                  removing
                    ? "security.removeDeviceDialogDescription"
                    : "security.signOutDialogDescription"
                }
                ns="settings"
                values={{ deviceName: pendingEnd?.label ?? t("security.unknownDevice") }}
                components={{ bold: <span className="font-medium" /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("security.revokeDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => pendingEnd && endSignedIn.mutate(pendingEnd)}
              disabled={endSignedIn.isPending}
            >
              {endSignedIn.isPending
                ? t("security.revoking")
                : removing
                  ? t("security.removeDeviceConfirm")
                  : t("security.signOutConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmSweep} onOpenChange={() => setConfirmSweep(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("security.signOutOthersDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("security.signOutOthersDialogDescription", { count: endable.length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("security.revokeDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => revokeOthers.mutate()}
              disabled={revokeOthers.isPending}
            >
              {revokeOthers.isPending ? t("security.revoking") : t("security.signOutOthersConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsSection>
  );
};

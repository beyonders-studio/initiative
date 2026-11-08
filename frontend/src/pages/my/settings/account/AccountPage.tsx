import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useServer } from "@/hooks/useServer";
import { getUserHandle } from "@/lib/userDisplay";
import { HeldChangeNotice } from "@/pages/my/settings/HeldChangeNotice";
import { Button } from "@/ui/button";

import { AddressManager } from "./AddressManager";
import { DeleteAccountDialog } from "./DeleteAccountDialog";

interface UserSettingsAccountPageProps {
  user: UserRead;
  logout: () => void | Promise<void>;
}

/**
 * The account: who it is, where it is reached, and how you leave.
 *
 * Separate from Settings › Profile, which is the face other people see, and
 * from Settings › Security, which holds every way in. Ways out come last, in
 * increasing order of consequence.
 */
export const AccountPage = ({ user, logout }: UserSettingsAccountPageProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const { isNativePlatform, getServerHostname, clearServerUrl } = useServer();
  const router = useRouter();
  // Deactivate and Delete open the same dialog at their own step.
  const [leaving, setLeaving] = useState<"deactivate" | "soft_delete" | null>(null);

  return (
    <div className="space-y-6">
      <HeldChangeNotice />
      <SettingsSection title={t("profile.usernameLabel")} description={t("profile.usernameHelp")}>
        <p className="font-medium">{getUserHandle(user)}</p>
      </SettingsSection>

      <SettingsSection title={t("addresses.title")} description={t("addresses.description")}>
        <AddressManager />
      </SettingsSection>

      {isNativePlatform ? (
        <SettingsSection
          title={t("dangerZone.serverConnection")}
          description={`${t("dangerZone.connectedTo", { hostname: getServerHostname() })} ${t(
            "dangerZone.disconnectDescription"
          )}`}
          action={
            <Button
              variant="outline"
              onClick={async () => {
                await logout();
                clearServerUrl();
                router.navigate({ to: "/login", replace: true });
              }}
            >
              {t("dangerZone.disconnectButton")}
            </Button>
          }
        />
      ) : null}

      <SettingsSection destructive title={t("dangerZone.title")}>
        <SettingsRow
          label={t("dangerZone.deactivateTitle")}
          description={t("dangerZone.deactivateDescription")}
          action={
            <Button variant="outline" onClick={() => setLeaving("deactivate")}>
              {t("dangerZone.deactivateButton")}
            </Button>
          }
        />
        <SettingsRow
          label={t("dangerZone.permanentDeleteTitle")}
          description={
            <>
              {t("dangerZone.permanentDeleteDescriptionText")}{" "}
              <strong>{t("dangerZone.cannotBeUndone")}</strong>
            </>
          }
          action={
            <Button variant="destructive" onClick={() => setLeaving("soft_delete")}>
              {t("dangerZone.deleteButton")}
            </Button>
          }
        />
      </SettingsSection>

      <DeleteAccountDialog
        open={leaving !== null}
        onOpenChange={(open) => {
          if (!open) setLeaving(null);
        }}
        onSuccess={() => {
          setLeaving(null);
          logout();
          router.navigate({ to: "/login" });
        }}
        user={user}
        initialAction={leaving ?? undefined}
      />
    </div>
  );
};

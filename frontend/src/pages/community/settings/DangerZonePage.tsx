import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { deleteCommunity } from "@/api/generated/communities/communities";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

export const DangerZonePage = () => {
  const { activeCommunity, communities, refreshCommunities, switchCommunity } = useCommunities();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation(["communities", "common"]);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [password, setPassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Some accounts are not asked for a password — they hold none, or the
  // deployment signs nobody in with one. The server asks for a recent sign-in
  // instead, so the field is hidden. An account still on its way in is asked,
  // as it is today.
  const passwordless = user?.password_required === false;

  // The whole phrase is uppercased, including the community name, so casing
  // never trips up the confirmation. Mirrors the backend check.
  const expectedPhrase = activeCommunity
    ? `DELETE COMMUNITY ${activeCommunity.name.toUpperCase()}`
    : "";

  const resetDialog = () => {
    setPassword("");
    setDeleteError(null);
  };

  const removal = useApiMutation(
    {
      mutationFn: (communityId: number) =>
        // The dialog's confirm is enabled only once the typed phrase matches this
        // one exactly, so it is the phrase that was typed.
        deleteCommunity(communityId, {
          password,
          confirmation_text: expectedPhrase,
        }),
    },
    {
      onMutate: () => setDeleteError(null),
      // Deletion is confirmed (204) and irreversible. Move off the deleted community's
      // URL onto a surviving community: switchCommunity updates the active-community context +
      // storage, so we never land on (or reload into) the now-dangling community id —
      // which is what produced the blank "not a member" screen. Best-effort — a
      // refresh hiccup must not surface a misleading "unable to delete" for a community
      // that is already gone. SPA navigation (not window.location) avoids racing the
      // storage write that a full reload would re-read.
      onSuccess: async (_data, deletedId) => {
        const nextCommunity = communities.find((g) => g.id !== deletedId);
        try {
          if (nextCommunity) {
            await switchCommunity(nextCommunity.id);
          } else {
            await refreshCommunities();
          }
        } catch (error) {
          console.error(error);
        }
        await navigate({ to: "/" });
      },
      onError: (error) =>
        setDeleteError(getErrorMessage(error, "communities:settings.unableToDelete")),
    }
  );

  if (!activeCommunity) {
    return (
      <div className="space-y-6">
        <h2 className="font-semibold text-xl tracking-tight">{t("settings.dangerZone")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveCommunity")}</p>
      </div>
    );
  }

  const deletionList = (
    <ul className="list-inside list-disc space-y-1 text-sm">
      <li>{t("settings.deleteWhatInitiatives")}</li>
      <li>{t("settings.deleteWhatProjects")}</li>
      <li>{t("settings.deleteWhatTasks")}</li>
      <li>{t("settings.deleteWhatFiles")}</li>
      <li>{t("settings.deleteWhatMembers")}</li>
      <li>{t("settings.deleteWhatSettings")}</li>
    </ul>
  );

  return (
    <div className="space-y-6">
      <SettingsSection
        title={t("settings.deleteCommunityTitle")}
        description={t("settings.dangerDescription")}
        className="border-destructive/50"
      >
        <p className="text-sm">
          <Trans
            i18nKey="settings.deleteCommunityIntro"
            ns="communities"
            values={{ name: activeCommunity.name }}
            components={{ bold: <strong /> }}
          />
        </p>
        {deletionList}
        <Button
          variant="destructive"
          onClick={() => {
            resetDialog();
            setShowDeleteConfirm(true);
          }}
          disabled={removal.isPending}
        >
          {removal.isPending ? t("settings.deleting") : t("settings.deleteCommunity")}
        </Button>
      </SettingsSection>

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={(open) => {
          setShowDeleteConfirm(open);
          if (!open) resetDialog();
        }}
        title={t("settings.deleteConfirmTitle")}
        description={
          <Trans
            i18nKey="settings.deleteConfirmDescription"
            ns="communities"
            values={{ name: activeCommunity.name }}
            components={{ bold: <strong /> }}
          />
        }
        confirmationText={expectedPhrase}
        confirmationLabel={
          <Trans
            i18nKey="settings.deleteConfirmLabel"
            ns="communities"
            values={{ phrase: expectedPhrase }}
            components={{ bold: <strong /> }}
          />
        }
        confirmLabel={t("common:delete")}
        loadingLabel={t("settings.deleting")}
        isLoading={removal.isPending}
        confirmDisabled={!passwordless && password.length === 0}
        destructive
        onConfirm={(e) => {
          // Keep the dialog open so inline errors (wrong password)
          // stay visible; the confirm button closes it by default.
          e.preventDefault();
          removal.mutate(activeCommunity.id);
        }}
      >
        {!passwordless && (
          <Field label={t("settings.deleteConfirmPasswordLabel")}>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("settings.deleteConfirmPasswordPlaceholder")}
              autoComplete="current-password"
            />
          </Field>
        )}
        {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
      </ConfirmDialog>
    </div>
  );
};

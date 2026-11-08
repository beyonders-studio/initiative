import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { deleteCommunity } from "@/api/generated/communities/communities";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
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
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

export const SettingsCommunityDangerZonePage = () => {
  const { activeCommunity, communities, refreshCommunities, switchCommunity } = useCommunities();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation(["communities", "common"]);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [password, setPassword] = useState("");
  const [deleting, setDeleting] = useState(false);
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
  const canConfirmDelete =
    deleteConfirmText === expectedPhrase && (passwordless || password.length > 0);

  const resetDialog = () => {
    setDeleteConfirmText("");
    setPassword("");
    setDeleteError(null);
  };

  const confirmDeleteCommunity = async () => {
    if (!activeCommunity) {
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteCommunity(activeCommunity.id, {
        password,
        confirmation_text: deleteConfirmText,
      });
    } catch (error) {
      console.error(error);
      setDeleteError(getErrorMessage(error, "communities:settings.unableToDelete"));
      setDeleting(false);
      return;
    }
    // Deletion is confirmed (204) and irreversible. Move off the deleted community's
    // URL onto a surviving community: switchCommunity updates the active-community context +
    // storage, so we never land on (or reload into) the now-dangling community id —
    // which is what produced the blank "not a member" screen. Best-effort — a
    // refresh hiccup must not surface a misleading "unable to delete" for a community
    // that is already gone. SPA navigation (not window.location) avoids racing the
    // storage write that a full reload would re-read.
    const nextCommunity = communities.find((g) => g.id !== activeCommunity.id);
    try {
      if (nextCommunity) {
        await switchCommunity(nextCommunity.id);
      } else {
        await refreshCommunities();
      }
    } catch (error) {
      console.error(error);
    }
    void navigate({ to: "/" });
  };

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
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle>{t("settings.deleteCommunityTitle")}</CardTitle>
          <CardDescription>{t("settings.dangerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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
            disabled={deleting}
          >
            {deleting ? t("settings.deleting") : t("settings.deleteCommunity")}
          </Button>
        </CardContent>
      </Card>

      <AlertDialog
        open={showDeleteConfirm}
        onOpenChange={(open) => {
          setShowDeleteConfirm(open);
          if (!open) resetDialog();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="settings.deleteConfirmDescription"
                ns="communities"
                values={{ name: activeCommunity.name }}
                components={{ bold: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-4 py-2">
            {!passwordless && (
              <div className="space-y-2">
                <Label htmlFor="delete-community-password">
                  {t("settings.deleteConfirmPasswordLabel")}
                </Label>
                <Input
                  id="delete-community-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("settings.deleteConfirmPasswordPlaceholder")}
                  autoComplete="current-password"
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="delete-community-confirm-input">
                <Trans
                  i18nKey="settings.deleteConfirmLabel"
                  ns="communities"
                  values={{ phrase: expectedPhrase }}
                  components={{ bold: <strong /> }}
                />
              </Label>
              <Input
                id="delete-community-confirm-input"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={expectedPhrase}
                autoComplete="off"
              />
            </div>
            {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                // Keep the dialog open so inline errors (wrong password)
                // stay visible; AlertDialogAction closes on click by default.
                e.preventDefault();
                void confirmDeleteCommunity();
              }}
              disabled={!canConfirmDelete || deleting}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {deleting ? t("settings.deleting") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

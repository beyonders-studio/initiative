import { Trans, useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";

interface DeleteInitiativeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initiativeName: string;
  isDeleting: boolean;
  onConfirm: () => void;
}

/**
 * The single delete-initiative confirmation flow: a type-the-name-to-confirm
 * guard before the whole tree (projects, docs, events) is soft-deleted
 * to trash. Shared by the per-initiative settings page and the community settings
 * Initiatives table so there is exactly one delete workflow to maintain. The
 * caller owns the mutation (via onConfirm/isDeleting); this only gates it.
 *
 * A thin wrapper over the shared ConfirmDialog's type-to-confirm mode.
 */
export const DeleteInitiativeDialog = ({
  open,
  onOpenChange,
  initiativeName,
  isDeleting,
  onConfirm,
}: DeleteInitiativeDialogProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("settings.deleteConfirmTitle")}
      description={
        <Trans
          i18nKey="settings.deleteConfirmDescription"
          ns="initiatives"
          values={{ name: initiativeName }}
          components={{ bold: <strong /> }}
        />
      }
      confirmationText={initiativeName}
      confirmationLabel={
        <Trans
          i18nKey="settings.deleteConfirmLabel"
          ns="initiatives"
          values={{ name: initiativeName }}
          components={{ bold: <strong /> }}
        />
      }
      confirmLabel={t("common:delete")}
      loadingLabel={t("settings.deletingInitiative")}
      cancelLabel={t("common:cancel")}
      onConfirm={onConfirm}
      isLoading={isDeleting}
      destructive
    />
  );
};

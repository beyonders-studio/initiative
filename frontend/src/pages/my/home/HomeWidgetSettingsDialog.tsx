/**
 * One widget's options. Each change is saved as it is made — the widget behind
 * the dialog shows it at once — so there is nothing to confirm, only to close.
 */

import { useTranslation } from "react-i18next";

import { HOME_WIDGETS } from "@/components/home/widgets";
import type { HomeWidget, HomeWidgetOptions } from "@/lib/home/layout";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/ui/dialog";

export interface HomeWidgetSettingsDialogProps {
  widget: HomeWidget | null;
  onClose: () => void;
  onChange: (id: string, options: HomeWidgetOptions) => void;
}

export function HomeWidgetSettingsDialog({
  widget,
  onClose,
  onChange,
}: HomeWidgetSettingsDialogProps) {
  const { t } = useTranslation(["home", "common"]);
  const Settings = widget ? HOME_WIDGETS[widget.type].Settings : undefined;

  return (
    <Dialog
      open={widget !== null && Settings !== undefined}
      onOpenChange={(open) => !open && onClose()}
    >
      {/* The widget's own form is the whole description. */}
      <DialogContent aria-describedby={undefined}>
        {widget && Settings ? (
          <>
            <DialogHeader>
              <DialogTitle>
                {t("settingsDialog.title", { title: t(`widgets.${widget.type}.title`) })}
              </DialogTitle>
            </DialogHeader>
            <Settings
              options={widget.options ?? {}}
              onChange={(options) => onChange(widget.id, options)}
            />
            <DialogFooter>
              <Button type="button" onClick={onClose}>
                {t("common:done")}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Every widget the home page can hold, to add one. A widget that may appear
 * only once and is already on the page is shown, and says so, rather than
 * vanishing from the list.
 */

import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HOME_WIDGETS } from "@/components/home/widgets";
import { canAddWidget, type HomeLayout } from "@/lib/home/layout";
import { HOME_WIDGET_TYPES, type HomeWidgetType } from "@/lib/home/widgetTypes";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { cn } from "@/ui/lib/utils";

export interface AddHomeWidgetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  layout: HomeLayout;
  onAdd: (type: HomeWidgetType) => void;
}

export function AddHomeWidgetDialog({
  open,
  onOpenChange,
  layout,
  onAdd,
}: AddHomeWidgetDialogProps) {
  const { t } = useTranslation("home");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("picker.title")}</DialogTitle>
          <DialogDescription>{t("picker.description")}</DialogDescription>
        </DialogHeader>
        <ul className="grid grid-cols-fill-56/2 gap-2">
          {HOME_WIDGET_TYPES.map((type) => {
            const { icon: Icon } = HOME_WIDGETS[type];
            const available = canAddWidget(layout, type);
            const placed = layout.widgets.some((widget) => widget.type === type);
            return (
              <li key={type}>
                <button
                  type="button"
                  disabled={!available}
                  onClick={() => {
                    onAdd(type);
                    onOpenChange(false);
                  }}
                  className={cn(
                    "flex h-full w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                    available ? "hover:bg-accent" : "cursor-not-allowed opacity-60"
                  )}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                    <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-sm">{t(`widgets.${type}.title`)}</span>
                    <span className="block text-muted-foreground text-xs">
                      {t(`widgets.${type}.description`)}
                    </span>
                    {placed && !available ? (
                      <span className="mt-1 flex items-center gap-1 text-muted-foreground text-xs">
                        <Check className="size-3" aria-hidden="true" />
                        {t("picker.onPage")}
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

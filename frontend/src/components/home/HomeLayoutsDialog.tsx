/**
 * The starting layouts, each drawn as a small map of where its widgets sit.
 *
 * Two uses. From the view tabs, picking one opens it as a new view beside the
 * others, so nothing the reader arranged is lost, and a blank page is one of
 * the choices. From an empty view, picking one fills that view.
 *
 * More are in the marketplace, which the dialog sends the reader to rather
 * than lists: a page of them is a choice of its own.
 */

import { Link } from "@tanstack/react-router";
import { LayoutTemplate, type LucideIcon, Store, Timer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HOME_WIDGETS } from "@/components/home/widgets";
import { HOME_GRID_COLUMNS, type HomeLayout, type HomeWidget } from "@/lib/home/layout";
import { HOME_PRESET_IDS, type HomePresetId, presetLayout } from "@/lib/home/presets";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { WizardOption } from "@/ui/wizard-dialog";

export type HomeLayoutChoice = HomePresetId | "blank";

export interface HomeLayoutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `new` makes a view; `fill` fills the empty one on screen. */
  mode: "new" | "fill";
  onPick: (choice: HomeLayoutChoice) => void;
}

/** The icon a widget shows on a map: what it is set to, where that is the point of it. */
const mapIcon = (widget: HomeWidget): LucideIcon => {
  if (widget.type === "clock" && widget.options?.mode === "timer") return Timer;
  return HOME_WIDGETS[widget.type].icon;
};

/**
 * Where each widget of a layout sits, at a glance. Every map is the same
 * size, however long its page, so the choices line up side by side; each
 * widget takes its share of the width and of the page's height.
 */
export function LayoutMap({ layout }: { layout: HomeLayout }) {
  const rows = Math.max(1, ...layout.widgets.map((widget) => widget.grid.y + widget.grid.h));
  return (
    <div aria-hidden="true" className="h-28 rounded-md bg-muted/50 p-1">
      <div className="relative h-full w-full">
        {layout.widgets.map((widget) => {
          const Icon = mapIcon(widget);
          return (
            <div
              key={widget.id}
              className="absolute p-px"
              style={{
                left: `${(widget.grid.x / HOME_GRID_COLUMNS) * 100}%`,
                width: `${(widget.grid.w / HOME_GRID_COLUMNS) * 100}%`,
                top: `${(widget.grid.y / rows) * 100}%`,
                height: `${(widget.grid.h / rows) * 100}%`,
              }}
            >
              <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-sm border bg-background text-muted-foreground">
                {widget.grid.h / rows > 0.12 ? <Icon className="size-3.5" /> : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function HomeLayoutsDialog({ open, onOpenChange, mode, onPick }: HomeLayoutsDialogProps) {
  const { t } = useTranslation("home");
  const choices: HomeLayoutChoice[] =
    mode === "new" ? [...HOME_PRESET_IDS, "blank"] : [...HOME_PRESET_IDS];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(mode === "new" ? "layouts.newTitle" : "layouts.fillTitle")}</DialogTitle>
          <DialogDescription>
            {t(mode === "new" ? "layouts.newDescription" : "layouts.fillDescription")}
          </DialogDescription>
        </DialogHeader>
        <ul className="grid grid-cols-fill-56/3 gap-3">
          {choices.map((choice) => (
            <li key={choice}>
              <WizardOption
                className="h-full flex-col items-stretch"
                icon={
                  choice === "blank" ? (
                    <div
                      aria-hidden="true"
                      className="flex h-28 items-center justify-center rounded-md border border-dashed bg-muted/50 text-muted-foreground"
                    >
                      <LayoutTemplate className="size-5" />
                    </div>
                  ) : (
                    <LayoutMap layout={presetLayout(choice)} />
                  )
                }
                title={choice === "blank" ? t("views.blank.name") : t(`presets.${choice}.name`)}
                description={
                  choice === "blank"
                    ? t("views.blank.description")
                    : t(`presets.${choice}.description`)
                }
                onClick={() => {
                  onPick(choice);
                  onOpenChange(false);
                }}
              />
            </li>
          ))}
        </ul>

        <div className="flex justify-center">
          <Button asChild variant="outline">
            <Link to="/marketplace" onClick={() => onOpenChange(false)}>
              <Store className="size-4" aria-hidden="true" />
              {t("marketplace.browse")}
            </Link>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

import { Check, ImageIcon, LayoutTemplate, Pencil, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { invalidate, q } from "@/api/query-keys";
import { type HomeLayoutChoice, HomeLayoutsDialog } from "@/components/home/HomeLayoutsDialog";
import { HomeActionsContext } from "@/components/home/homeActions";
import { HOME_WIDGETS } from "@/components/home/widgets";
import { useAuth } from "@/hooks/useAuth";
import { useHomeViews } from "@/hooks/useHomeViews";
import { useMyDecorations } from "@/hooks/useUsers";
import type { HomeWidget, HomeWidgetOptions } from "@/lib/home/layout";
import {
  addWidget,
  applyGrid,
  canAddWidget,
  HOME_LAYOUT_VERSION,
  type HomeLayout,
  moveWidget,
  removeWidget,
  setViewBanner,
  setWidgetOptions,
} from "@/lib/home/layout";
import { presetLayout } from "@/lib/home/presets";
import { HOME_WIDGET_TYPES, type HomeWidgetType } from "@/lib/home/widgetTypes";
import { decorationSrc, resolveDecoration } from "@/lib/profileDecorations";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/ui/empty";
import { atLeast, useRegionWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { PullToRefresh } from "@/ui/pull-to-refresh";
import { Skeleton } from "@/ui/skeleton";
import { WizardOption } from "@/ui/wizard-dialog";

import { HomeBannerDialog } from "./HomeBannerDialog";
import { HomeCanvas } from "./HomeCanvas";
import { HomeViewBanner } from "./HomeViewBanner";
import { HomeViewTabs } from "./HomeViewTabs";

interface HomeWidgetSettingsDialogProps {
  widget: HomeWidget | null;
  onClose: () => void;
  onChange: (id: string, options: HomeWidgetOptions) => void;
}

function HomeWidgetSettingsDialog({ widget, onClose, onChange }: HomeWidgetSettingsDialogProps) {
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

interface AddHomeWidgetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  layout: HomeLayout;
  onAdd: (type: HomeWidgetType) => void;
}

function AddHomeWidgetDialog({ open, onOpenChange, layout, onAdd }: AddHomeWidgetDialogProps) {
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
                <WizardOption
                  disabled={!available}
                  onClick={() => {
                    onAdd(type);
                    onOpenChange(false);
                  }}
                  className="h-full items-start"
                  icon={
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                      <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
                    </span>
                  }
                  title={t(`widgets.${type}.title`)}
                  description={
                    <>
                      {t(`widgets.${type}.description`)}
                      {placed && !available ? (
                        <span className="mt-1 flex items-center gap-1">
                          <Check className="size-3" aria-hidden="true" />
                          {t("picker.onPage")}
                        </span>
                      ) : null}
                    </>
                  }
                />
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

export const HomePage = () => {
  const { t } = useTranslation(["home", "common"]);
  const home = useHomeViews();
  const { layout, isLoaded, updateLayout } = home;
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [choosingLayout, setChoosingLayout] = useState<"new" | "fill" | null>(null);
  const [configuring, setConfiguring] = useState<string | null>(null);
  const [choosingBanner, setChoosingBanner] = useState(false);
  const { user } = useAuth();
  const [region, setRegion] = useState<HTMLDivElement | null>(null);
  // The grid needs room for two widgets side by side; narrower, they stack.
  const wide = atLeast(useRegionWidthClass(region), "md");

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allTasks(), q.allCalendars(), q.userStats());
  }, []);

  const actions = useMemo(() => ({ customize: () => setEditing(true) }), []);

  // The view's banner, while the reader still has it: the library is the
  // answer to that, so it is asked only once there is a banner to check.
  const library = useMyDecorations({ enabled: Boolean(layout.banner) });
  const wearsBanner = library.data?.items.some(
    (item) => item.kind === "banner" && item.id === layout.banner
  );
  const bannerArt = wearsBanner ? resolveDecoration(layout.banner, "banner") : undefined;
  const bannerSrc = bannerArt
    ? decorationSrc(bannerArt, user?.profile_decorations?.grad_year)
    : null;

  const empty = layout.widgets.length === 0;
  const configuringWidget = layout.widgets.find((widget) => widget.id === configuring) ?? null;

  const pickLayout = (choice: HomeLayoutChoice) => {
    const start: HomeLayout =
      choice === "blank" ? { version: HOME_LAYOUT_VERSION, widgets: [] } : presetLayout(choice);
    if (choosingLayout === "fill") {
      updateLayout(() => start);
    } else {
      home.create(choice === "blank" ? t("views.blank.name") : t(`presets.${choice}.name`), start);
    }
  };

  // The tabs show for more than one view, or while customizing (where the
  // first new one is made); with none, the controls are just the button.
  const showsBar = home.views.views.length > 1 || editing;

  // The view tabs and the page's controls: at the top of the page, or riding
  // on the view's banner when it wears one.
  const controls = (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {/* A real basis, not `flex-1`'s zero, so a narrow screen wraps the
            buttons under the tabs rather than squeezing the tabs to nothing. */}
        {isLoaded && showsBar ? (
          <div className="min-w-0 shrink grow basis-64">
            <HomeViewTabs
              views={home.views}
              activeId={home.activeId}
              editing={editing}
              onSelect={home.select}
              onNew={() => setChoosingLayout("new")}
              onRename={home.rename}
              onDuplicate={home.duplicate}
              onMove={home.move}
              onDelete={home.remove}
            />
          </div>
        ) : null}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {editing ? (
            <>
              <Button type="button" variant="outline" size="sm" onClick={() => setAdding(true)}>
                <Plus className="size-4" aria-hidden="true" />
                {t("addWidget")}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setChoosingBanner(true)}
              >
                <ImageIcon className="size-4" aria-hidden="true" />
                {t("banner.open")}
              </Button>
              <Button type="button" size="sm" onClick={() => setEditing(false)}>
                <Check className="size-4" aria-hidden="true" />
                {t("common:done")}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setEditing(true)}
              disabled={!isLoaded}
              // Alone on a banner, the button carries its own frosted ground.
              className={cn(bannerSrc && !showsBar && "bg-background/80 backdrop-blur")}
            >
              <Pencil className="size-4" aria-hidden="true" />
              {t("customize")}
            </Button>
          )}
        </div>
      </div>
      {editing ? (
        <p className="text-muted-foreground text-sm">
          {wide ? t("editing.hint") : t("editing.hintStacked")}
        </p>
      ) : null}
    </>
  );

  return (
    <HomeActionsContext.Provider value={actions}>
      <PullToRefresh onRefresh={handleRefresh}>
        <div ref={setRegion} className="space-y-4">
          <h1 className="sr-only">{t("title")}</h1>
          <div className="space-y-4">
            {/* One tree whether or not the view wears a banner, so the banner
                arriving never remounts the tabs (and whatever dialog they have
                open). On a banner the controls ride at its top on a frosted
                ground — a bar only when there are tabs to put on it — whose
                padding is taken back out of its margin, so the tab bar sits
                where it does on a view with no banner. */}
            <HomeViewBanner imageUrl={bannerSrc}>
              <div
                className={cn(
                  "space-y-2",
                  bannerSrc &&
                    showsBar &&
                    "-m-2 rounded-xl bg-background/80 p-2 shadow-sm backdrop-blur"
                )}
              >
                {controls}
              </div>
            </HomeViewBanner>
            {/* The widgets rise over the lower half of a banner as it fades. */}
            <div className={cn("relative z-10 space-y-4", bannerSrc && "-mt-28 md:-mt-36")}>
              {!isLoaded ? (
                // The layout is the reader's own; drawing the default first would
                // mount a page of widgets only to swap them for theirs.
                <div className="space-y-4" aria-busy="true">
                  <Skeleton className="h-24 w-full rounded-xl" />
                  <Skeleton className="h-64 w-full rounded-xl" />
                </div>
              ) : empty ? (
                <Empty className="border border-dashed">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <LayoutTemplate />
                    </EmptyMedia>
                    <EmptyTitle>{t("empty.title")}</EmptyTitle>
                    <EmptyDescription>{t("empty.description")}</EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent className="flex-row flex-wrap justify-center">
                    <Button type="button" onClick={() => setAdding(true)}>
                      <Plus className="size-4" aria-hidden="true" />
                      {t("addWidget")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setChoosingLayout("fill")}
                    >
                      <LayoutTemplate className="size-4" aria-hidden="true" />
                      {t("empty.fromLayout")}
                    </Button>
                  </EmptyContent>
                </Empty>
              ) : (
                <HomeCanvas
                  // A view's grid starts from its own layout, not the last one's.
                  key={home.activeId}
                  layout={layout}
                  editing={editing}
                  wide={wide}
                  onArrange={(placed) => updateLayout((current) => applyGrid(current, placed))}
                  onMove={(id, step) => updateLayout((current) => moveWidget(current, id, step))}
                  onRemove={(id) => updateLayout((current) => removeWidget(current, id))}
                  onConfigure={setConfiguring}
                  onOptionsChange={(id, options) =>
                    updateLayout((current) => setWidgetOptions(current, id, options))
                  }
                />
              )}
            </div>
          </div>
        </div>

        <HomeBannerDialog
          open={choosingBanner}
          onOpenChange={setChoosingBanner}
          value={layout.banner ?? null}
          onChange={(next) => updateLayout((current) => setViewBanner(current, next))}
        />
        <AddHomeWidgetDialog
          open={adding}
          onOpenChange={setAdding}
          layout={layout}
          onAdd={(type) => updateLayout((current) => addWidget(current, type))}
        />
        <HomeLayoutsDialog
          open={choosingLayout !== null}
          onOpenChange={(open) => {
            if (!open) setChoosingLayout(null);
          }}
          mode={choosingLayout ?? "new"}
          onPick={pickLayout}
        />
        <HomeWidgetSettingsDialog
          widget={configuringWidget}
          onClose={() => setConfiguring(null)}
          onChange={(id, options) =>
            updateLayout((current) => setWidgetOptions(current, id, options))
          }
        />
      </PullToRefresh>
    </HomeActionsContext.Provider>
  );
};

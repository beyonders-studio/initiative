/**
 * `/settings/reading` — how this wiki reads.
 *
 * A handbook is read front to back and ordered by hand; a world bible has two
 * hundred entries nobody orders by hand; a runbook is full of screenshots and
 * wants the whole screen. These are the choices that let one tool be all three,
 * so they sit together in one section rather than being scattered over the
 * surface people read.
 *
 * Every control saves on its own. There is no combination of these that has to
 * be applied at once, so there is nothing to submit.
 */

import { useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { WikiPageOrder, WikiReadingWidth } from "@/api/generated/initiativeAPI.schemas";
import { useUpdateWiki, useWiki } from "@/hooks/useWikis";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Separator } from "@/ui/separator";
import { Switch } from "@/ui/switch";

/** What the picker opens on when the wiki has no accent of its own. */
const DEFAULT_ACCENT = "#6366F1";

/** How many heading levels the contents list may show. */
const DEPTHS = [2, 3, 4] as const;

/** A labelled row: the control on the right, what it does underneath. */
const Setting = ({
  label,
  hint,
  control,
  className,
}: {
  label: string;
  hint?: string;
  control: ReactNode;
  className?: string;
}) => (
  <div className={cn("flex items-start justify-between gap-4 py-3", className)}>
    <div className="min-w-0 space-y-0.5">
      <p className="font-medium text-sm">{label}</p>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
    <div className="shrink-0">{control}</div>
  </div>
);

export const WikiReadingSettingsPage = () => {
  const { t } = useTranslation("wikis");
  const { wikiId } = useParams({ strict: false }) as { wikiId?: string };
  const parsedId = wikiId ? Number(wikiId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const wikiQuery = useWiki(isValidId ? parsedId : null);
  const update = useUpdateWiki(parsedId);

  const wiki = wikiQuery.data;

  if (!wiki) {
    return <p className="text-muted-foreground text-sm">{t("loading")}</p>;
  }

  const canWrite = wiki.can.edit;
  const save = (patch: Parameters<typeof update.mutate>[0]) => {
    if (canWrite) update.mutate(patch);
  };

  const orders = [
    {
      value: WikiPageOrder.manual,
      label: t("settings.orderManual"),
      hint: t("settings.orderManualHint"),
    },
    {
      value: WikiPageOrder.title,
      label: t("settings.orderTitle"),
      hint: t("settings.orderTitleHint"),
    },
    {
      value: WikiPageOrder.recently_updated,
      label: t("settings.orderRecent"),
      hint: t("settings.orderRecentHint"),
    },
  ];

  const widths = [
    {
      value: WikiReadingWidth.wide,
      label: t("settings.widthWide"),
      hint: t("settings.widthWideHint"),
    },
    {
      value: WikiReadingWidth.comfortable,
      label: t("settings.widthComfortable"),
      hint: t("settings.widthComfortableHint"),
    },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.order")}</CardTitle>
          <CardDescription>{t("settings.orderDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={wiki.page_order}
            onValueChange={(value) => save({ page_order: value as WikiPageOrder })}
            disabled={!canWrite}
            className="gap-2"
          >
            {orders.map((option) => (
              <div key={option.value} className="flex items-start gap-2.5">
                <RadioGroupItem
                  value={option.value}
                  id={`wiki-order-${option.value}`}
                  className="mt-0.5"
                />
                <Label htmlFor={`wiki-order-${option.value}`} className="space-y-0.5">
                  <span className="font-normal text-sm">{option.label}</span>
                  <span className="block text-muted-foreground text-xs">{option.hint}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.reading")}</CardTitle>
          <CardDescription>{t("settings.readingDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <RadioGroup
            value={wiki.reading_width}
            onValueChange={(value) => save({ reading_width: value as WikiReadingWidth })}
            disabled={!canWrite}
            className="gap-2"
          >
            {widths.map((option) => (
              <div key={option.value} className="flex items-start gap-2.5">
                <RadioGroupItem
                  value={option.value}
                  id={`wiki-width-${option.value}`}
                  className="mt-0.5"
                />
                <Label htmlFor={`wiki-width-${option.value}`} className="space-y-0.5">
                  <span className="font-normal text-sm">{option.label}</span>
                  <span className="block text-muted-foreground text-xs">{option.hint}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>

          <Separator className="my-2" />

          <Setting
            label={t("settings.contents")}
            hint={t("settings.contentsDescription")}
            control={
              <Select
                value={String(wiki.contents_depth)}
                onValueChange={(value) => save({ contents_depth: Number(value) })}
                disabled={!canWrite}
              >
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEPTHS.map((depth) => (
                    <SelectItem key={depth} value={String(depth)}>
                      {t("settings.contentsLevels", { count: depth })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />

          <Separator />

          <Setting
            label={t("settings.updated")}
            hint={t("settings.updatedHint")}
            control={
              <Switch
                checked={wiki.show_updated_at}
                onCheckedChange={(checked) => save({ show_updated_at: checked })}
                disabled={!canWrite}
                aria-label={t("settings.updated")}
              />
            }
          />

          <Separator />

          <Setting
            label={t("settings.connections")}
            hint={t("settings.connectionsHint")}
            control={
              <Switch
                checked={wiki.show_connections}
                onCheckedChange={(checked) => save({ show_connections: checked })}
                disabled={!canWrite}
                aria-label={t("settings.connections")}
              />
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.appearance")}</CardTitle>
          <CardDescription>{t("settings.appearanceDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Setting
            label={t("settings.accent")}
            hint={t("settings.accentHint")}
            className="items-center"
            control={
              <div className="flex items-center gap-2">
                {/* The picker's trigger is `w-full` by default, sized for a
                    form column; here it sits in a row that hugs its content,
                    so it is given a width of its own and the button beside it
                    stays on the card. */}
                <ColorPickerPopover
                  value={wiki.accent_color ?? DEFAULT_ACCENT}
                  onChangeComplete={(colour) => save({ accent_color: colour })}
                  disabled={!canWrite}
                  triggerLabel={t("settings.accent")}
                  className="w-40"
                />
                {wiki.accent_color ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8"
                    disabled={!canWrite}
                    onClick={() => save({ accent_color: null })}
                  >
                    {t("settings.accentNone")}
                  </Button>
                ) : null}
              </div>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
};

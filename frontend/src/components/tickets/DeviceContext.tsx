/**
 * The device and page a help request or feedback is sent from: the app's
 * version, the platform, the language, the theme, the page and the window's
 * width. Shown before sending, and left out at the sender's choice. Nothing in
 * it names a person or a thing: the page is its route, with every id left out.
 */

import { Capacitor } from "@capacitor/core";
import { useMatches } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DeviceContext } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";
import { useWidthClass } from "@/hooks/useWidthClass";
import { cn } from "@/lib/utils";

/** The fields, in the order they are shown. */
const FIELDS = ["app_version", "platform", "locale", "theme", "route", "viewport"] as const;

/** A route id as a template: the pathless layout segments dropped, every id
 *  left as the parameter that names it. */
export const routeTemplate = (routeId: string): string => {
  const kept = routeId.split("/").filter((segment) => segment && !segment.startsWith("_"));
  return `/${kept.join("/")}`;
};

/** The template of the page showing now. */
export const useRouteTemplate = (): string =>
  routeTemplate(useMatches({ select: (matches) => matches.at(-1)?.routeId ?? "" }));

/** This device and the page showing now. */
export const useDeviceContext = (): DeviceContext => {
  const { i18n } = useTranslation();
  const { theme } = useTheme();
  const width = useWidthClass();
  const route = useRouteTemplate();
  return {
    app_version: __APP_VERSION__,
    platform: Capacitor.getPlatform(),
    locale: i18n.language,
    theme,
    route,
    viewport: width,
  };
};

/** The fields as a list, each labelled. */
export const DeviceContextFields = ({
  context,
  className,
}: {
  context: DeviceContext;
  className?: string;
}) => {
  const { t } = useTranslation("intake");
  const shown = FIELDS.filter((field) => context[field]);
  return (
    <dl className={cn("grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs", className)}>
      {shown.map((field) => (
        <div key={field} className="contents">
          <dt className="text-muted-foreground">{t(`feedback.context.fields.${field}`)}</dt>
          <dd className="break-all font-mono">{context[field]}</dd>
        </div>
      ))}
    </dl>
  );
};

export interface DeviceContextPreviewProps {
  context: DeviceContext;
  onRemove: () => void;
}

/** What will be sent, in a box of its own, removed with one click. */
export const DeviceContextPreview = ({ context, onRemove }: DeviceContextPreviewProps) => {
  const { t } = useTranslation("intake");
  if (!FIELDS.some((field) => context[field])) return null;
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-sm">{t("feedback.context.title")}</p>
        <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
          <X className="h-4 w-4" aria-hidden="true" />
          {t("feedback.context.remove")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("feedback.context.help")}</p>
      <DeviceContextFields context={context} />
    </div>
  );
};

/**
 * The device and page a help request or feedback is sent from: the app's
 * version, the platform, the language, the theme, the page and the window's
 * width. Shown before sending, and left out at the sender's choice. Nothing in
 * it names a person or a thing: the page is its route, with every id left out.
 */

import { Capacitor } from "@capacitor/core";
import { useMatches } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DeviceContext } from "@/api/generated/initiativeAPI.schemas";
import { useTheme } from "@/hooks/useTheme";
import { Button } from "@/ui/button";
import { useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Switch } from "@/ui/switch";

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

/**
 * One line saying whether the device's details go with it, a switch to leave
 * them out, and a look at what they are.
 */
export const DeviceContextSwitch = ({
  context,
  included,
  onIncludedChange,
  disabled,
}: {
  context: DeviceContext;
  included: boolean;
  onIncludedChange: (included: boolean) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("intake");
  const [seeing, setSeeing] = useState(false);
  return (
    <>
      <div className="flex items-center gap-2 text-muted-foreground text-xs">
        <Switch
          checked={included}
          onCheckedChange={onIncludedChange}
          aria-label={t("feedback.context.switch")}
          disabled={disabled}
        />
        <span className="min-w-0 flex-1">
          {included ? t("feedback.context.on") : t("feedback.context.off")}
        </span>
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-muted-foreground text-xs"
          aria-expanded={seeing}
          onClick={() => setSeeing(!seeing)}
        >
          {seeing ? t("feedback.context.hide") : t("feedback.context.show")}
        </Button>
      </div>
      {seeing ? (
        <dl
          className={cn(
            "grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-md bg-muted p-2 text-xs",
            !included && "line-through opacity-50"
          )}
        >
          {FIELDS.filter((field) => context[field]).map((field) => (
            <div key={field} className="contents">
              <dt className="text-muted-foreground">{t(`feedback.context.fields.${field}`)}</dt>
              <dd className="break-all font-mono">{context[field]}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </>
  );
};

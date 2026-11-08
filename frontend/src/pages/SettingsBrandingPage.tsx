import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { useInterfaceSettings, useUpdateInterfaceSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Switch } from "@/ui/switch";

export const SettingsBrandingPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const interfaceQuery = useInterfaceSettings({ enabled: canManagePlatformConfig });

  // Both colours are picked and then saved together, so a refetch between the
  // picking and the saving must not put the old pair back.
  const form = useServerForm(
    interfaceQuery.data,
    (settings) => ({
      light: settings?.light_accent_color ?? "#2563eb",
      dark: settings?.dark_accent_color ?? "#60a5fa",
    }),
    "interface"
  );

  const updateInterface = useUpdateInterfaceSettings({
    onSuccess: () => toast.success(t("branding.interfaceSuccess")),
  });

  // The chooser is the other half of what a visitor meets before they sign in,
  // which is why it is set here. It saves on the switch rather than with the
  // colours: one decision, answered by moving it.
  const cookieConsentEnabled = interfaceQuery.data?.cookie_consent_enabled ?? false;
  const setCookieConsent = (enabled: boolean) =>
    updateInterface.mutate({
      light_accent_color: form.values.light,
      dark_accent_color: form.values.dark,
      cookie_consent_enabled: enabled,
    });

  const handleInterfaceSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sent = form.values;
    updateInterface.mutate(
      { light_accent_color: sent.light, dark_accent_color: sent.dark },
      { onSuccess: () => form.settle(sent) }
    );
  };

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("branding.platformOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("branding.colorsTitle")}</CardTitle>
          <CardDescription>{t("branding.colorsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {interfaceQuery.isLoading ? (
            <SkeletonRegion label={t("branding.loadingInterface")}>
              <FormSkeleton card={false} fields={2} />
            </SkeletonRegion>
          ) : interfaceQuery.isError ? (
            <p className="text-destructive text-sm">{t("branding.interfaceError")}</p>
          ) : (
            <form className="grid grid-cols-pair gap-6" onSubmit={handleInterfaceSubmit}>
              <Field
                label={t("branding.lightModeLabel")}
                hint={t("branding.lightModeHelp")}
                className="space-y-3 rounded-lg border p-4"
              >
                <ColorPickerPopover
                  value={form.values.light}
                  onChange={(next) => form.set({ light: next })}
                  triggerLabel={t("branding.adjust")}
                />
              </Field>

              <Field
                label={t("branding.darkModeLabel")}
                hint={t("branding.darkModeHelp")}
                className="space-y-3 rounded-lg border p-4"
              >
                <ColorPickerPopover
                  value={form.values.dark}
                  onChange={(next) => form.set({ dark: next })}
                  triggerLabel={t("branding.adjust")}
                />
              </Field>

              <CardFooter className="col-span-full flex flex-wrap gap-3 p-0 pt-2">
                <Button type="submit" disabled={updateInterface.isPending}>
                  {updateInterface.isPending
                    ? t("branding.savingInterface")
                    : t("branding.saveInterface")}
                </Button>
              </CardFooter>
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("branding.cookieConsent.title")}</CardTitle>
          <CardDescription>{t("branding.cookieConsent.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Switch
              id="cookie-consent-enabled"
              checked={cookieConsentEnabled}
              disabled={interfaceQuery.isLoading || updateInterface.isPending}
              onCheckedChange={(checked) => setCookieConsent(Boolean(checked))}
            />
            <Label htmlFor="cookie-consent-enabled">
              {t("branding.cookieConsent.toggleLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">{t("branding.cookieConsent.helpText")}</p>
          {/* Off is not a way to skip the question — an owner is entitled to
              know what the switch actually decides before they touch it. */}
          <p className="text-muted-foreground text-xs">{t("branding.cookieConsent.scopeNote")}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("branding.yonderPlayground.title")}</CardTitle>
          <CardDescription>{t("branding.yonderPlayground.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast(t("branding.yonderPlayground.default.message"))}
            >
              {t("branding.yonderPlayground.default.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.success(t("branding.yonderPlayground.success.message"))}
            >
              {t("branding.yonderPlayground.success.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.error(t("branding.yonderPlayground.error.message"))}
            >
              {t("branding.yonderPlayground.error.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.warning(t("branding.yonderPlayground.warning.message"))}
            >
              {t("branding.yonderPlayground.warning.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.info(t("branding.yonderPlayground.info.message"))}
            >
              {t("branding.yonderPlayground.info.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.loading(t("branding.yonderPlayground.loading.message"))}
            >
              {t("branding.yonderPlayground.loading.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.success(t("branding.yonderPlayground.withDescription.message"), {
                  description: t("branding.yonderPlayground.withDescription.detail"),
                })
              }
            >
              {t("branding.yonderPlayground.withDescription.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.info(t("branding.yonderPlayground.withAction.message"), {
                  action: {
                    label: t("branding.yonderPlayground.withAction.actionLabel"),
                    onClick: () =>
                      toast.success(t("branding.yonderPlayground.withAction.reverted")),
                  },
                })
              }
            >
              {t("branding.yonderPlayground.withAction.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast.warning(t("branding.yonderPlayground.sticky.message"), {
                  id: "yonder-sticky",
                  duration: Infinity,
                });
              }}
            >
              {t("branding.yonderPlayground.sticky.label")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => toast.dismiss("yonder-sticky")}>
              {t("branding.yonderPlayground.dismissSticky")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast.promise(new Promise((resolve) => setTimeout(() => resolve("done"), 2000)), {
                  loading: t("branding.yonderPlayground.promiseResolve.loading"),
                  success: t("branding.yonderPlayground.promiseResolve.success"),
                  error: t("branding.yonderPlayground.promiseReject.errorPrefix", {
                    message: "",
                  }),
                });
              }}
            >
              {t("branding.yonderPlayground.promiseResolve.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast
                  .promise(
                    new Promise((_, reject) => setTimeout(() => reject(new Error("boom")), 2000)),
                    {
                      loading: t("branding.yonderPlayground.promiseReject.loading"),
                      success: t("branding.yonderPlayground.promiseResolve.success"),
                      error: (err) =>
                        t("branding.yonderPlayground.promiseReject.errorPrefix", {
                          message: (err as Error).message,
                        }),
                    }
                  )
                  .catch(() => undefined);
              }}
            >
              {t("branding.yonderPlayground.promiseReject.label")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => toast.dismiss()}>
              {t("branding.yonderPlayground.dismissAll")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

/**
 * Platform → Authentication: which ways in the deployment permits.
 *
 * The ones that can *begin* a session. A second factor accompanies a sign-in
 * rather than opening one, so it is asked about on Platform → Security beside
 * the rule it answers — the split is the server's own `primary` flag, not a
 * list kept here.
 *
 * Written here and enforced server-side, so what this page does is offer the
 * choice and state what it costs — never decide it.
 */

import { isAxiosError } from "axios";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { LoginMethod } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { usePlatformAuthSettings, useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Checkbox } from "@/ui/checkbox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Label } from "@/ui/label";

/** The two refusals that come with a number to acknowledge. */
const ACKNOWLEDGEABLE = new Set([
  "SETTINGS_LOGIN_METHODS_WOULD_STRAND",
  "SETTINGS_LOGIN_METHODS_STALE_ACK",
]);

/**
 * How many accounts a refused write would leave without a way in, as the
 * server counted them — null when it refused for some other reason.
 *
 * The figure comes back on the refusal itself, in `X-Affected-Count`. It is
 * taken over the whole change rather than a method at a time, so an account
 * holding two of the credentials being withdrawn is counted once.
 */
const strandedByServer = (error: unknown): number | null => {
  if (!isAxiosError(error)) return null;
  if (!ACKNOWLEDGEABLE.has(getErrorCode(error) ?? "")) return null;
  const counted = Number(error.response?.headers?.["x-affected-count"]);
  return Number.isInteger(counted) && counted > 0 ? counted : null;
};

export const PlatformAuthSection = () => {
  const { t } = useTranslation("settings");
  const query = usePlatformAuthSettings();
  // The change the server has asked to have acknowledged, with its number.
  const [pending, setPending] = useState<{ methods: LoginMethod[]; stranded: number } | null>(null);

  const updateMethods = useUpdatePlatformAuthSettings({
    onSuccess: () => toast.success(t("auth.methods.saved")),
    onError: (err, variables) => {
      // A refusal that names a number is the server asking for it back, so it
      // is the one the dialog shows and the one the next write sends.
      const stranded = strandedByServer(err);
      if (stranded !== null) {
        setPending({ methods: variables.methods ?? [], stranded });
        return;
      }
      setPending(null);
      toast.error(getErrorMessage(err, "settings:auth.methods.saveError"));
    },
  });
  if (query.isLoading || !query.data) return null;

  const { methods, communities_requiring_sign_in } = query.data;

  const enabled = methods.filter((m) => m.enabled).map((m) => m.method);
  const busy = updateMethods.isPending;

  /**
   * Send the change. The first attempt acknowledges nothing: a change that
   * would leave somebody without a way in comes back refused, carrying the
   * count, and it is that count the confirmed write sends.
   */
  const applyMethods = (next: LoginMethod[], acknowledge?: number) =>
    updateMethods.mutate({
      methods: next,
      ...(acknowledge === undefined ? {} : { acknowledge_stranded: acknowledge }),
    });

  const toggleMethod = (method: LoginMethod, checked: boolean) =>
    applyMethods(checked ? [...enabled, method] : enabled.filter((m) => m !== method));

  return (
    <>
      <SettingsSection title={t("auth.methods.title")} description={t("auth.methods.description")}>
        <div className="space-y-4">
          {methods
            .filter((entry) => entry.primary)
            .map((entry) => {
              // The last permitted way in cannot be withdrawn: the deployment
              // must keep at least one, which the server holds too.
              const isLastEnabled = entry.enabled && enabled.length === 1;
              return (
                <div key={entry.method} className="flex items-start gap-3">
                  <Checkbox
                    id={`login-method-${entry.method}`}
                    checked={entry.enabled}
                    disabled={busy || isLastEnabled}
                    onCheckedChange={(checked) => toggleMethod(entry.method, Boolean(checked))}
                    className="mt-0.5"
                  />
                  <div className="space-y-1">
                    <Label
                      htmlFor={`login-method-${entry.method}`}
                      className="cursor-pointer font-medium"
                    >
                      {t(`auth.methods.${entry.method}.label`)}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t(`auth.methods.${entry.method}.help`)}
                    </p>
                    {isLastEnabled ? (
                      <p className="text-muted-foreground text-xs">
                        {t("auth.methods.lastRemaining")}
                      </p>
                    ) : null}
                    {entry.enabled && entry.would_strand > 0 ? (
                      <p className="text-amber-600 text-xs dark:text-amber-500">
                        {t("auth.methods.wouldStrand", { count: entry.would_strand })}
                      </p>
                    ) : null}
                    {entry.method === "sso" &&
                    entry.enabled &&
                    communities_requiring_sign_in > 0 ? (
                      <p className="text-amber-600 text-xs dark:text-amber-500">
                        {t("auth.methods.communitiesRequire", {
                          count: communities_requiring_sign_in,
                        })}
                      </p>
                    ) : null}
                  </div>
                </div>
              );
            })}
        </div>
      </SettingsSection>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={t("auth.methods.confirmTitle")}
        description={t("auth.methods.confirmBody", { count: pending?.stranded ?? 0 })}
        confirmLabel={t("auth.methods.confirmAction")}
        destructive
        isLoading={updateMethods.isPending}
        onConfirm={() => {
          if (pending) applyMethods(pending.methods, pending.stranded);
        }}
      />
    </>
  );
};

import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useStartVendorSetup } from "@/hooks/usePluginServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { postToVendor } from "@/lib/pluginServices";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { CopyButton } from "@/ui/copy-button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { localized } from "@/ui/lib/localized";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { SecretInput } from "@/ui/secret-input";

/** A save the plug-in's vendor check refused: the fields it blames, what to
 *  say, and what the vendor holds instead when the check says. */
export interface VendorRefusal {
  fields: string[];
  text: string;
  shows: string | null;
}

export interface VendorClientSectionProps {
  registration: PluginServiceRegistrationRead;
  /** The values typed so far, by key; a key left out keeps what is stored. */
  values: Record<string, string>;
  /** `undefined` takes the key out again, keeping what is stored: an empty
   *  secret field means the saved secret stays, where sending it empty would
   *  clear it. */
  onValueChange: (key: string, value: string | undefined) => void;
  plain?: boolean;
  refusal?: VendorRefusal | null;
}

/**
 * The client the plug-in's vendor issued for this server, as the listing asks
 * for it.
 *
 * Where the listing offers the vendor's own setup, that comes first: it
 * creates the client at the vendor and writes every value back, so there is
 * nothing to copy. Entering the values by hand is the other way, in the order
 * it happens at the vendor: register this server's addresses there, then type
 * what the vendor issued. A secret is never shown again once saved.
 *
 * Once every value is set, the values come first and making a new client at
 * the vendor folds away: it would replace them. A save the plug-in's vendor
 * check refused marks the fields it blames.
 */
export const VendorClientSection = ({
  registration,
  values,
  onValueChange,
  plain,
  refusal,
}: VendorClientSectionProps) => {
  const { t, i18n } = useTranslation("settings");
  const hasSetup = registration.vendor_setup === "github_app_manifest";
  const blamed = new Set(refusal?.fields ?? []);
  const [manualOpen, setManualOpen] = useState(false);
  // Who owns the app the vendor's setup creates: the operator's own GitHub
  // account, or an organization they administer, which GitHub's address names.
  const [owner, setOwner] = useState<"account" | "organization">("account");
  const [organization, setOrganization] = useState("");
  const missingOrganization = owner === "organization" && !organization.trim();
  const [setupError, setSetupError] = useState<string | null>(null);
  const startSetup = useStartVendorSetup();

  const handleVendorSetup = () => {
    setSetupError(null);
    startSetup.mutate(
      {
        registrationId: registration.id,
        organization: owner === "organization" ? organization.trim() : "",
      },
      {
        onSuccess: postToVendor,
        onError: (error) =>
          setSetupError(getErrorMessage(error, "settings:pluginServices.vendorSetupError")),
      }
    );
  };

  const addresses = [
    { label: t("pluginServices.callbackUrlLabel"), value: registration.connection_callback_url },
    { label: t("pluginServices.setupUrlLabel"), value: registration.connection_setup_url },
    { label: t("pluginServices.webhookUrlLabel"), value: registration.webhook_url },
  ];

  const manual = (
    <ol className="list-decimal space-y-6 pl-5 marker:font-medium marker:text-sm">
      <li className="space-y-3">
        <div className="space-y-1">
          <h4 className="font-medium text-sm">{t("pluginServices.redirectTitle")}</h4>
          <p className="text-muted-foreground text-sm">{t("pluginServices.redirectHelp")}</p>
        </div>
        <dl className="divide-y rounded-md border">
          {addresses.map((address) => (
            <div key={address.label} className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3">
              <dt className="w-36 shrink-0 font-medium text-sm">{address.label}</dt>
              <dd className="min-w-0 flex-1 basis-64 break-all font-mono text-xs">
                {address.value}
              </dd>
              <CopyButton
                value={address.value}
                label={t("pluginServices.composeCopy")}
                aria-label={t("pluginServices.copyAddress", { label: address.label })}
              />
            </div>
          ))}
        </dl>
      </li>

      <li className="space-y-3">
        <div className="space-y-1">
          <h4 className="font-medium text-sm">{t("pluginServices.vendorValuesTitle")}</h4>
          <p className="text-muted-foreground text-sm">{t("pluginServices.vendorValuesHelp")}</p>
        </div>
        {refusal && (
          <div
            role="alert"
            className="space-y-1 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm"
          >
            <p>{refusal.text}</p>
            {refusal.shows && (
              <p className="text-muted-foreground">
                {t("pluginServices.vendorCheckShows")}{" "}
                <span className="font-mono text-foreground">{refusal.shows}</span>
              </p>
            )}
          </div>
        )}
        <div className="grid grid-cols-pair gap-4">
          {registration.vendor_fields.map((field) => {
            const id = `plugin-service-vendor-${field.key}`;
            const isSecret = field.type === "secret";
            const isSet = registration.vendor_set.includes(field.key);
            const typed = values[field.key];
            const value = typed ?? (isSecret ? "" : (registration.vendor_values[field.key] ?? ""));
            return (
              // A secret may be a PEM key, which spans lines, so it takes the
              // whole row.
              <div key={field.key} className={isSecret ? "col-span-full space-y-2" : "space-y-2"}>
                <Label htmlFor={id}>
                  {localized(field.label, i18n.language) ?? field.key}
                  {field.required && <span aria-hidden> *</span>}
                </Label>
                {isSecret ? (
                  <SecretInput
                    multiline
                    id={id}
                    aria-invalid={blamed.has(field.key) || undefined}
                    saved={isSet}
                    value={value}
                    onValueChange={(next) => onValueChange(field.key, next || undefined)}
                    placeholder={t("pluginServices.vendorEmpty")}
                  />
                ) : (
                  <Input
                    id={id}
                    aria-invalid={blamed.has(field.key) || undefined}
                    type={field.type === "url" ? "url" : "text"}
                    value={value}
                    onChange={(event) => onValueChange(field.key, event.target.value)}
                    placeholder={t("pluginServices.vendorEmpty")}
                    autoComplete="off"
                    spellCheck={false}
                  />
                )}
              </div>
            );
          })}
        </div>
      </li>
    </ol>
  );

  const setup = (
    <section
      className="space-y-3 rounded-md border bg-muted/40 p-4"
      aria-label={t("pluginServices.vendorSetupTitle")}
    >
      <div className="space-y-1">
        <h4 className="font-medium text-sm">{t("pluginServices.vendorSetupTitle")}</h4>
        <p className="text-muted-foreground text-sm">
          {t(
            registration.vendor_ready
              ? "pluginServices.vendorSetupHelpReplace"
              : "pluginServices.vendorSetupHelp"
          )}
        </p>
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-2 font-medium text-sm">
          {t("pluginServices.vendorSetupOwnerLabel")}
        </legend>
        <RadioGroup
          value={owner}
          onValueChange={(value) => setOwner(value as "account" | "organization")}
          className="gap-2"
        >
          {(["account", "organization"] as const).map((choice) => (
            <div key={choice} className="flex items-start gap-3">
              <RadioGroupItem id={`vendor-owner-${choice}`} value={choice} className="mt-1" />
              <div className="space-y-0.5">
                <Label htmlFor={`vendor-owner-${choice}`}>
                  {t(`pluginServices.vendorSetupOwner.${choice}.label`)}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t(`pluginServices.vendorSetupOwner.${choice}.help`)}
                </p>
              </div>
            </div>
          ))}
        </RadioGroup>
        {owner === "organization" && (
          <Field
            className="max-w-sm pl-7"
            label={t("pluginServices.vendorSetupOrganizationLabel")}
            hint={t("pluginServices.vendorSetupOrganizationHelp")}
          >
            <Input
              value={organization}
              onChange={(event) => setOrganization(event.target.value)}
              placeholder="my-org"
              maxLength={39}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        )}
      </fieldset>
      <Button
        type="button"
        onClick={handleVendorSetup}
        disabled={startSetup.isPending || missingOrganization}
      >
        {startSetup.isPending
          ? t("pluginServices.vendorSetupStarting")
          : t("pluginServices.vendorSetupCreate")}
      </Button>
      {setupError && <p className="text-destructive text-xs">{setupError}</p>}
    </section>
  );

  return (
    <SettingsSection
      plain={plain}
      title={t("pluginServices.vendorTitle")}
      description={t("pluginServices.vendorHelp")}
      action={
        registration.vendor_ready ? (
          <Badge variant="outline" className="border-transparent bg-emerald-600 text-white">
            {t("pluginServices.vendorReadyBadge")}
          </Badge>
        ) : (
          <Badge variant="warning">{t("pluginServices.vendorMissingBadge")}</Badge>
        )
      }
    >
      {hasSetup && !registration.vendor_ready ? (
        <>
          {setup}

          <Collapsible open={manualOpen || Boolean(refusal)} onOpenChange={setManualOpen}>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="group -ml-2">
                <ChevronRight
                  className="size-4 transition-transform group-data-[state=open]:rotate-90"
                  aria-hidden="true"
                />
                {t("pluginServices.vendorManualTitle")}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">{manual}</CollapsibleContent>
          </Collapsible>
        </>
      ) : hasSetup ? (
        <>
          {manual}

          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="group -ml-2">
                <ChevronRight
                  className="size-4 transition-transform group-data-[state=open]:rotate-90"
                  aria-hidden="true"
                />
                {t("pluginServices.vendorSetupReplaceTitle")}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">{setup}</CollapsibleContent>
          </Collapsible>
        </>
      ) : (
        manual
      )}
    </SettingsSection>
  );
};

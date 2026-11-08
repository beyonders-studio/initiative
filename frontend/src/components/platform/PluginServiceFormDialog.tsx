import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PluginServicePublishedKey,
  PluginServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useConnectPluginService,
  usePluginServiceKeys,
  useStartVendorSetup,
} from "@/hooks/usePluginServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { parseAllowedOrigins, postToVendor } from "@/lib/pluginServices";
import { localized } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import { CopyButton } from "@/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

/** What the operator stated, before it is shaped into a create or a patch. */
export interface PluginServiceFormValues {
  publicId: string;
  baseUrl: string;
  /** Where a browser loads the plug-in, or "" when that is the base URL too. */
  pageOrigin: string;
  allowedOrigins: string[];
  /** Parsed JWKS, or null to leave the stored key set untouched. */
  jwks: Record<string, unknown> | null;
  /** Where the plug-in publishes its key set, or "" for none. */
  jwksUri: string;
  mandatory: boolean;
  operationsOnly: boolean;
  /** One vendor installation may connect to several communities. */
  sharedRoutes: boolean;
  /** Vendor values that were typed, by key. "" clears one; a key left out is kept. */
  vendorValues: Record<string, string>;
}

interface FormState {
  publicId: string;
  baseUrl: string;
  pageOrigin: string;
  allowedOrigins: string;
  jwks: string;
  jwksUri: string;
  mandatory: boolean;
  operationsOnly: boolean;
  sharedRoutes: boolean;
  vendorValues: Record<string, string>;
}

const EMPTY_FORM: FormState = {
  publicId: "",
  baseUrl: "",
  pageOrigin: "",
  allowedOrigins: "",
  jwks: "",
  jwksUri: "",
  mandatory: false,
  operationsOnly: false,
  sharedRoutes: false,
  vendorValues: {},
};

export interface PluginServiceFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The registration being edited, or null to register a new one. */
  editing: PluginServiceRegistrationRead | null;
  saving: boolean;
  onSubmit: (values: PluginServiceFormValues) => void;
}

/**
 * Give one plug-in service its deployment facts. What the plug-in is and may do comes
 * from its listing, and is not edited here.
 *
 * Its keys are public keys, either pasted as a key set or fetched from the
 * address the plug-in publishes them at. Connect reads the set the plug-in serves at
 * its saved base URL, shows each key's fingerprint, and pins the set once the
 * operator confirms it. The one secret a registration holds is
 * what the operator supplies for the plug-in's vendor client, as the plug-in's listing
 * asks for it: a secret value is written here and never shown again. A listing
 * may also offer the vendor's own setup, which creates the client at the
 * vendor and writes its values back without anyone copying them.
 *
 * A container's listing may carry the Compose service its publisher wrote. It
 * is shown as text to copy, and its address pre-fills the base URL.
 */
export const PluginServiceFormDialog = ({
  open,
  onOpenChange,
  editing,
  saving,
  onSubmit,
}: PluginServiceFormDialogProps) => {
  const { t, i18n } = useTranslation("settings");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  // Only whether the paste is JSON at all. Whether it is a key set we could
  // verify against is the server's answer, and it gives a message code.
  const [jwksError, setJwksError] = useState<string | null>(null);
  // The keys Connect read, waiting for the operator to confirm them.
  const [servedKeys, setServedKeys] = useState<PluginServicePublishedKey[] | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  // The key set box's text as Connect left it, to tell a pinned set from one
  // the operator pasted.
  const [pinnedJwks, setPinnedJwks] = useState<string | null>(null);
  // The GitHub organization to own the app the vendor's setup creates.
  const [organization, setOrganization] = useState("");
  const [setupError, setSetupError] = useState<string | null>(null);
  const readKeys = usePluginServiceKeys();
  const connect = useConnectPluginService();
  const startSetup = useStartVendorSetup();

  // Re-seed whenever the dialog opens, so a reopened form never shows the
  // previous row's values.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        publicId: editing.public_id,
        baseUrl: editing.base_url ?? editing.compose_base_url ?? "",
        pageOrigin: editing.page_origin ?? "",
        allowedOrigins: editing.allowed_origins.join("\n"),
        jwks: editing.jwks ? JSON.stringify(editing.jwks, null, 2) : "",
        jwksUri: editing.jwks_uri ?? "",
        mandatory: editing.mandatory,
        operationsOnly: editing.operations_only,
        sharedRoutes: editing.shared_routes,
        vendorValues: {},
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setJwksError(null);
    setServedKeys(null);
    setConnectError(null);
    setPinnedJwks(null);
    setOrganization("");
    setSetupError(null);
  }, [open, editing]);

  // Connect reads from the saved base URL, so it waits while the box holds
  // another one.
  const baseUrlEdited =
    editing !== null && form.baseUrl.trim().replace(/\/+$/, "") !== (editing.base_url ?? "");

  const handleReadKeys = () => {
    if (!editing) return;
    setServedKeys(null);
    setConnectError(null);
    readKeys.mutate(editing.id, {
      onSuccess: setServedKeys,
      onError: (error) =>
        setConnectError(getErrorMessage(error, "settings:pluginServices.connectError")),
    });
  };

  const handleConnect = () => {
    if (!editing || !servedKeys) return;
    connect.mutate(
      // Exactly what was shown, so the server stores only that.
      { registrationId: editing.id, keys: servedKeys },
      {
        onSuccess: (registration) => {
          const pinned = registration.jwks ? JSON.stringify(registration.jwks, null, 2) : "";
          setPinnedJwks(pinned);
          setForm((prev) => ({
            ...prev,
            jwks: pinned,
            // Connect clears the key set address; saving must not put it back.
            jwksUri: registration.jwks_uri ?? "",
          }));
          setServedKeys(null);
          toast.success(t("pluginServices.connected"));
        },
        onError: (error) => {
          // A set that changed has to be read and checked again.
          setServedKeys(null);
          setConnectError(getErrorMessage(error, "settings:pluginServices.connectError"));
        },
      }
    );
  };

  const handleVendorSetup = () => {
    if (!editing) return;
    setSetupError(null);
    startSetup.mutate(
      { registrationId: editing.id, organization: organization.trim() },
      {
        onSuccess: postToVendor,
        onError: (error) =>
          setSetupError(getErrorMessage(error, "settings:pluginServices.vendorSetupError")),
      }
    );
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    // An emptied box clears the stored set; an untouched one on a row that
    // never had a key leaves it alone. Both arrive as {} vs null respectively,
    // which is the distinction the PATCH reads.
    const typed = form.jwks.trim();
    let jwks: Record<string, unknown> | null = null;
    if (baseUrlEdited && pinnedJwks !== null && form.jwks === pinnedJwks) {
      // The pinned set is the old address's plug-in. Clear it, so the new address
      // is connected on its own.
      jwks = {};
    } else if (typed) {
      try {
        jwks = JSON.parse(typed) as Record<string, unknown>;
      } catch {
        setJwksError(t("pluginServices.jwksInvalid"));
        return;
      }
    } else if (editing?.jwks) {
      jwks = {};
    }
    setJwksError(null);

    onSubmit({
      jwks,
      publicId: form.publicId.trim(),
      baseUrl: form.baseUrl.trim(),
      pageOrigin: form.pageOrigin.trim(),
      allowedOrigins: parseAllowedOrigins(form.allowedOrigins),
      jwksUri: form.jwksUri.trim(),
      mandatory: form.mandatory,
      operationsOnly: form.operationsOnly,
      sharedRoutes: form.sharedRoutes,
      vendorValues: Object.fromEntries(
        Object.entries(form.vendorValues).map(([key, value]) => [key, value.trim()])
      ),
    });
  };

  const vendorFields = editing?.vendor_fields ?? [];
  const declarative = editing?.kind === "declarative";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("pluginServices.editTitle") : t("pluginServices.createTitle")}
          </DialogTitle>
          <DialogDescription>
            {editing ? t("pluginServices.editDescription") : t("pluginServices.createDescription")}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="plugin-service-public-id">{t("pluginServices.publicIdLabel")}</Label>
            <Input
              id="plugin-service-public-id"
              value={form.publicId}
              onChange={(event) => setForm((prev) => ({ ...prev, publicId: event.target.value }))}
              placeholder={t("pluginServices.publicIdPlaceholder")}
              maxLength={120}
              disabled={Boolean(editing)}
              required={!editing}
              autoComplete="off"
            />
            <p className="text-muted-foreground text-xs">
              {editing ? t("pluginServices.publicIdHelpEdit") : t("pluginServices.publicIdHelp")}
            </p>
          </div>

          {/* A declarative plug-in runs nowhere and signs nothing: only its
              vendor values and its switches apply. */}
          {!declarative && (
            <>
              {editing?.compose_service && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor="plugin-service-compose">
                      {t("pluginServices.composeLabel")}
                    </Label>
                    <CopyButton
                      value={editing.compose_service}
                      label={t("pluginServices.composeCopy")}
                      copiedMessage={t("pluginServices.composeCopied")}
                    />
                  </div>
                  <Textarea
                    id="plugin-service-compose"
                    value={editing.compose_service}
                    readOnly
                    rows={8}
                    className="whitespace-pre font-mono text-xs"
                    wrap="off"
                    spellCheck={false}
                  />
                  <p className="text-muted-foreground text-xs">{t("pluginServices.composeHelp")}</p>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="plugin-service-base-url">{t("pluginServices.baseUrlLabel")}</Label>
                <Input
                  id="plugin-service-base-url"
                  value={form.baseUrl}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, baseUrl: event.target.value }))
                  }
                  placeholder={t("pluginServices.baseUrlPlaceholder")}
                  maxLength={1000}
                  required
                />
                <p className="text-muted-foreground text-xs">{t("pluginServices.baseUrlHelp")}</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="plugin-service-page-origin">
                  {t("pluginServices.pageOriginLabel")}
                </Label>
                <Input
                  id="plugin-service-page-origin"
                  value={form.pageOrigin}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, pageOrigin: event.target.value }))
                  }
                  placeholder={t("pluginServices.pageOriginPlaceholder")}
                  maxLength={1000}
                />
                <p className="text-muted-foreground text-xs">
                  {t("pluginServices.pageOriginHelp")}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="plugin-service-origins">
                  {t("pluginServices.allowedOriginsLabel")}
                </Label>
                <Textarea
                  id="plugin-service-origins"
                  value={form.allowedOrigins}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, allowedOrigins: event.target.value }))
                  }
                  placeholder={t("pluginServices.allowedOriginsPlaceholder")}
                  rows={3}
                />
                <p className="text-muted-foreground text-xs">
                  {editing
                    ? t("pluginServices.allowedOriginsHelpEdit")
                    : t("pluginServices.allowedOriginsHelp")}
                </p>
              </div>

              <fieldset className="rounded-md border p-3">
                {/* Floated so the legend sits inside the border like the other headings. */}
                <legend className="float-left w-full font-medium text-sm">
                  {t("pluginServices.keysTitle")}
                </legend>
                <div className="clear-both space-y-3">
                  <p className="text-muted-foreground text-xs">{t("pluginServices.keysHelp")}</p>

                  {editing?.base_url && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-muted-foreground text-xs">
                          {t("pluginServices.connectHelp")}
                        </p>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={handleReadKeys}
                          disabled={baseUrlEdited || readKeys.isPending || connect.isPending}
                        >
                          {readKeys.isPending
                            ? t("pluginServices.connectReading")
                            : t("pluginServices.connect")}
                        </Button>
                      </div>
                      {baseUrlEdited && (
                        <p className="text-muted-foreground text-xs">
                          {t("pluginServices.connectSaveFirst")}
                        </p>
                      )}
                      {servedKeys && (
                        <section
                          className="space-y-2 rounded-md border p-3"
                          aria-label={t("pluginServices.connectKeysTitle")}
                        >
                          <p className="font-medium text-sm">
                            {t("pluginServices.connectKeysTitle")}
                          </p>
                          <p className="text-muted-foreground text-xs">
                            {t("pluginServices.connectKeysHelp")}
                          </p>
                          <ul className="space-y-1">
                            {servedKeys.map((key) => (
                              <li key={`${key.kid}:${key.fingerprint}`} className="text-xs">
                                <span className="text-muted-foreground">
                                  {t("pluginServices.connectKid", { kid: key.kid })}
                                </span>
                                <code className="block break-all font-mono">{key.fingerprint}</code>
                              </li>
                            ))}
                          </ul>
                          <div className="flex justify-end gap-2">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => setServedKeys(null)}
                              disabled={connect.isPending}
                            >
                              {t("pluginServices.connectDismiss")}
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              onClick={handleConnect}
                              disabled={baseUrlEdited || connect.isPending}
                            >
                              {connect.isPending
                                ? t("pluginServices.connectPinning")
                                : t("pluginServices.connectConfirm")}
                            </Button>
                          </div>
                        </section>
                      )}
                      {connectError && <p className="text-destructive text-xs">{connectError}</p>}
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="plugin-service-jwks">{t("pluginServices.jwksLabel")}</Label>
                    <Textarea
                      id="plugin-service-jwks"
                      value={form.jwks}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, jwks: event.target.value }))
                      }
                      rows={6}
                      className="font-mono text-xs"
                      placeholder={'{\n  "keys": [ … ]\n}'}
                    />
                    <p className="text-muted-foreground text-xs">{t("pluginServices.jwksHelp")}</p>
                    {jwksError && <p className="text-destructive text-xs">{jwksError}</p>}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="plugin-service-jwks-uri">
                      {t("pluginServices.jwksUriLabel")}
                    </Label>
                    <Input
                      id="plugin-service-jwks-uri"
                      value={form.jwksUri}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, jwksUri: event.target.value }))
                      }
                      placeholder={t("pluginServices.jwksUriPlaceholder")}
                      maxLength={1000}
                      autoComplete="off"
                    />
                    <p className="text-muted-foreground text-xs">
                      {t("pluginServices.jwksUriHelp")}
                    </p>
                  </div>
                </div>
              </fieldset>
            </>
          )}

          {editing && vendorFields.length > 0 && (
            <fieldset className="rounded-md border p-3">
              <legend className="float-left w-full font-medium text-sm">
                {t("pluginServices.vendorTitle")}
              </legend>
              <div className="clear-both space-y-3">
                <p className="text-muted-foreground text-xs">{t("pluginServices.vendorHelp")}</p>

                {editing.vendor_setup === "github_app_manifest" && (
                  <section
                    className="space-y-2 rounded-md border p-3"
                    aria-label={t("pluginServices.vendorSetupTitle")}
                  >
                    <p className="font-medium text-sm">{t("pluginServices.vendorSetupTitle")}</p>
                    <p className="text-muted-foreground text-xs">
                      {t("pluginServices.vendorSetupHelp")}
                    </p>
                    <Label htmlFor="plugin-service-vendor-organization">
                      {t("pluginServices.vendorSetupOrganizationLabel")}
                    </Label>
                    <Input
                      id="plugin-service-vendor-organization"
                      value={organization}
                      onChange={(event) => setOrganization(event.target.value)}
                      placeholder={t("pluginServices.vendorSetupOrganizationPlaceholder")}
                      maxLength={39}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <p className="text-muted-foreground text-xs">
                      {t("pluginServices.vendorSetupOrganizationHelp")}
                    </p>
                    <div className="flex justify-end">
                      <Button
                        type="button"
                        size="sm"
                        onClick={handleVendorSetup}
                        disabled={startSetup.isPending}
                      >
                        {startSetup.isPending
                          ? t("pluginServices.vendorSetupStarting")
                          : t("pluginServices.vendorSetupCreate")}
                      </Button>
                    </div>
                    {setupError && <p className="text-destructive text-xs">{setupError}</p>}
                  </section>
                )}

                {vendorFields.map((field) => {
                  const id = `plugin-service-vendor-${field.key}`;
                  const isSecret = field.type === "secret";
                  const isSet = editing.vendor_set.includes(field.key);
                  const typed = form.vendorValues[field.key];
                  const value = typed ?? (isSecret ? "" : (editing.vendor_values[field.key] ?? ""));
                  return (
                    <div key={field.key} className="space-y-2">
                      <Label htmlFor={id}>
                        {localized(field.label, i18n.language) ?? field.key}
                        {field.required && <span aria-hidden> *</span>}
                      </Label>
                      {/* A secret may be a PEM key, which spans lines. */}
                      {isSecret ? (
                        <Textarea
                          id={id}
                          value={value}
                          onChange={(event) =>
                            setForm((prev) => ({
                              ...prev,
                              vendorValues: {
                                ...prev.vendorValues,
                                [field.key]: event.target.value,
                              },
                            }))
                          }
                          rows={3}
                          className="font-mono text-xs"
                          placeholder={
                            isSet
                              ? t("pluginServices.vendorSecretSet")
                              : t("pluginServices.vendorEmpty")
                          }
                          autoComplete="off"
                          spellCheck={false}
                        />
                      ) : (
                        <Input
                          id={id}
                          type={field.type === "url" ? "url" : "text"}
                          value={value}
                          onChange={(event) =>
                            setForm((prev) => ({
                              ...prev,
                              vendorValues: {
                                ...prev.vendorValues,
                                [field.key]: event.target.value,
                              },
                            }))
                          }
                          placeholder={t("pluginServices.vendorEmpty")}
                          autoComplete="off"
                          spellCheck={false}
                        />
                      )}
                    </div>
                  );
                })}

                <div className="space-y-2">
                  <p className="font-medium text-sm">{t("pluginServices.redirectTitle")}</p>
                  <p className="text-muted-foreground text-xs">
                    {t("pluginServices.redirectHelp")}
                  </p>
                  <Label htmlFor="plugin-service-callback-url">
                    {t("pluginServices.callbackUrlLabel")}
                  </Label>
                  <Input
                    id="plugin-service-callback-url"
                    value={editing.connection_callback_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                  <Label htmlFor="plugin-service-setup-url">
                    {t("pluginServices.setupUrlLabel")}
                  </Label>
                  <Input
                    id="plugin-service-setup-url"
                    value={editing.connection_setup_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                  <Label htmlFor="plugin-service-webhook-url">
                    {t("pluginServices.webhookUrlLabel")}
                  </Label>
                  <Input
                    id="plugin-service-webhook-url"
                    value={editing.webhook_url}
                    readOnly
                    className="font-mono text-xs"
                    onFocus={(event) => event.target.select()}
                  />
                </div>

                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Label htmlFor="plugin-service-shared-routes" className="font-medium">
                      {t("pluginServices.sharedRoutesLabel")}
                    </Label>
                    <p className="text-muted-foreground text-xs">
                      {t("pluginServices.sharedRoutesHelp")}
                    </p>
                  </div>
                  <Switch
                    id="plugin-service-shared-routes"
                    checked={form.sharedRoutes}
                    onCheckedChange={(checked) =>
                      setForm((prev) => ({ ...prev, sharedRoutes: Boolean(checked) }))
                    }
                  />
                </div>
              </div>
            </fieldset>
          )}

          <div className="space-y-2 rounded-md border p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label htmlFor="plugin-service-operations-only" className="font-medium">
                  {t("pluginServices.operationsOnlyLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t("pluginServices.operationsOnlyHelp")}{" "}
                  {t("pluginServices.operationsMandatoryHelp")}
                </p>
              </div>
              <Switch
                id="plugin-service-operations-only"
                checked={form.operationsOnly}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, operationsOnly: Boolean(checked) }))
                }
              />
            </div>
          </div>

          <div className="space-y-2 rounded-md border border-amber-500/50 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label htmlFor="plugin-service-mandatory" className="font-medium">
                  {t("pluginServices.mandatoryLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">{t("pluginServices.mandatoryHelp")}</p>
              </div>
              <Switch
                id="plugin-service-mandatory"
                checked={form.mandatory}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, mandatory: Boolean(checked) }))
                }
              />
            </div>
          </div>

          <DialogFooter
            submitLabel={t("pluginServices.save")}
            pendingLabel={t("pluginServices.saving")}
            pending={saving}
          />
        </form>
      </DialogContent>
    </Dialog>
  );
};

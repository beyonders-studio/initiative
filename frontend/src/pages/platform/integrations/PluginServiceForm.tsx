import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  PluginAvailability,
  type PluginServicePublishedKey,
  type PluginServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CommunityPicker, type PickedCommunity } from "@/components/communities/CommunityPicker";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useConnectPluginService, usePluginServiceKeys } from "@/hooks/usePluginServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { parseAllowedOrigins, runsAService } from "@/lib/pluginServices";
import { Button } from "@/ui/button";
import { CopyButton } from "@/ui/copy-button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

import { PlatformConnectionsSection } from "./PlatformConnectionsSection";
import { VendorClientSection, type VendorRefusal } from "./VendorClientSection";

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
  /** The communities a beta plug-in reaches; sent only while it is beta. */
  betaCommunities: PickedCommunity[];
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
  betaCommunities: PickedCommunity[];
  vendorValues: Record<string, string>;
}

const seed = (editing: PluginServiceRegistrationRead | null): FormState => ({
  publicId: editing?.public_id ?? "",
  baseUrl: editing ? (editing.base_url ?? editing.compose_base_url ?? "") : "",
  pageOrigin: editing?.page_origin ?? "",
  allowedOrigins: editing?.allowed_origins.join("\n") ?? "",
  jwks: editing?.jwks ? JSON.stringify(editing.jwks, null, 2) : "",
  jwksUri: editing?.jwks_uri ?? "",
  mandatory: editing?.mandatory ?? false,
  betaCommunities: editing?.beta_communities ?? [],
  vendorValues: {},
});

export interface PluginServiceFormProps {
  /** The registration being edited, or null to register a new one. */
  editing: PluginServiceRegistrationRead | null;
  onSubmit: (values: PluginServiceFormValues) => void;
  /** Where the Save button goes, inside the form. */
  footer: ReactNode;
  /** Sections drawn as headings rather than cards, for a dialog. */
  plain?: boolean;
  /** What the plug-in's vendor check refused the last save for. */
  vendorRefusal?: VendorRefusal | null;
  /** Vendor values to start typed: those a save wrote unchecked. */
  initialVendorValues?: Record<string, string>;
}

/**
 * One plug-in service's deployment facts, as sections. What the plug-in is and
 * may do comes from its listing, and is not edited here. Seeded once, when it
 * mounts: whoever shows it remounts it to show saved values.
 *
 * Its keys are public keys, either pasted as a key set or fetched from the
 * address the plug-in publishes them at. Connect reads the set the plug-in serves at
 * its saved base URL, shows each key's fingerprint, and pins the set once the
 * operator confirms it. The one secret a registration holds is
 * what the operator supplies for the plug-in's vendor client, as the plug-in's listing
 * asks for it (`VendorClientSection`).
 *
 * A container's listing may carry the Compose service its publisher wrote. It
 * is shown as text to copy, and its address pre-fills the base URL.
 */
export const PluginServiceForm = ({
  editing,
  onSubmit,
  footer,
  plain,
  vendorRefusal,
  initialVendorValues,
}: PluginServiceFormProps) => {
  const { t } = useTranslation("settings");
  const [form, setForm] = useState<FormState>(() => ({
    ...seed(editing),
    vendorValues: { ...initialVendorValues },
  }));
  // Only whether the paste is JSON at all. Whether it is a key set we could
  // verify against is the server's answer, and it gives a message code.
  const [jwksError, setJwksError] = useState<string | null>(null);
  // The keys Connect read, waiting for the operator to confirm them.
  const [servedKeys, setServedKeys] = useState<PluginServicePublishedKey[] | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  // The key set box's text as Connect left it, to tell a pinned set from one
  // the operator pasted.
  const [pinnedJwks, setPinnedJwks] = useState<string | null>(null);
  const readKeys = usePluginServiceKeys();
  const connect = useConnectPluginService();

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
      betaCommunities: form.betaCommunities,
      vendorValues: Object.fromEntries(
        Object.entries(form.vendorValues).map(([key, value]) => [key, value.trim()])
      ),
    });
  };

  // A new registration is a container's until its listing says otherwise.
  const service = !editing || runsAService(editing);

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      {/* The identifier names the registration for good, so it is asked only
          when adding one. */}
      {!editing && (
        <Field label={t("pluginServices.publicIdLabel")} hint={t("pluginServices.publicIdHelp")}>
          <Input
            value={form.publicId}
            onChange={(event) => setForm((prev) => ({ ...prev, publicId: event.target.value }))}
            placeholder={t("pluginServices.publicIdPlaceholder")}
            maxLength={120}
            required
            autoComplete="off"
          />
        </Field>
      )}

      {/* Only a container runs somewhere and signs: for a declarative or a
          tool plug-in, only its vendor values and its reach apply. */}
      {service && (
        <>
          <SettingsSection plain={plain} title={t("pluginServices.placementTitle")}>
            {editing?.compose_service && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <Label htmlFor="plugin-service-compose">{t("pluginServices.composeLabel")}</Label>
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

            <div className="grid grid-cols-pair gap-4">
              <Field
                label={t("pluginServices.baseUrlLabel")}
                hint={t("pluginServices.baseUrlHelp")}
              >
                <Input
                  value={form.baseUrl}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, baseUrl: event.target.value }))
                  }
                  placeholder={t("pluginServices.baseUrlPlaceholder")}
                  maxLength={1000}
                  required
                />
              </Field>

              <Field
                label={t("pluginServices.pageOriginLabel")}
                hint={t("pluginServices.pageOriginHelp")}
              >
                <Input
                  value={form.pageOrigin}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, pageOrigin: event.target.value }))
                  }
                  placeholder={t("pluginServices.pageOriginPlaceholder")}
                  maxLength={1000}
                />
              </Field>
            </div>

            <Field
              label={t("pluginServices.allowedOriginsLabel")}
              hint={
                editing
                  ? t("pluginServices.allowedOriginsHelpEdit")
                  : t("pluginServices.allowedOriginsHelp")
              }
            >
              <Textarea
                value={form.allowedOrigins}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, allowedOrigins: event.target.value }))
                }
                placeholder={t("pluginServices.allowedOriginsPlaceholder")}
                rows={3}
              />
            </Field>
          </SettingsSection>

          <SettingsSection
            plain={plain}
            title={t("pluginServices.keysTitle")}
            description={t("pluginServices.keysHelp")}
          >
            {editing?.base_url && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="min-w-0 flex-1 basis-64 text-muted-foreground text-sm">
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
                    <p className="font-medium text-sm">{t("pluginServices.connectKeysTitle")}</p>
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

            <div className="grid grid-cols-pair gap-4">
              <Field
                label={t("pluginServices.jwksLabel")}
                hint={t("pluginServices.jwksHelp")}
                error={jwksError}
              >
                <Textarea
                  value={form.jwks}
                  onChange={(event) => setForm((prev) => ({ ...prev, jwks: event.target.value }))}
                  rows={6}
                  className="font-mono text-xs"
                  placeholder={'{\n  "keys": [ … ]\n}'}
                />
              </Field>

              <Field
                label={t("pluginServices.jwksUriLabel")}
                hint={t("pluginServices.jwksUriHelp")}
              >
                <Input
                  value={form.jwksUri}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, jwksUri: event.target.value }))
                  }
                  placeholder={t("pluginServices.jwksUriPlaceholder")}
                  maxLength={1000}
                  autoComplete="off"
                />
              </Field>
            </div>
          </SettingsSection>
        </>
      )}

      {editing && editing.vendor_fields.length > 0 && (
        <VendorClientSection
          plain={plain}
          registration={editing}
          values={form.vendorValues}
          onValueChange={(key, value) =>
            setForm((prev) => {
              const { [key]: _, ...rest } = prev.vendorValues;
              return {
                ...prev,
                vendorValues: value === undefined ? rest : { ...rest, [key]: value },
              };
            })
          }
          refusal={vendorRefusal}
        />
      )}

      {editing && editing.platform_connections.length > 0 && (
        <PlatformConnectionsSection plain={plain} registration={editing} />
      )}

      <SettingsSection plain={plain} title={t("pluginServices.reachTitle")}>
        {/* Who can use it is the plug-in's to say, in each release; the owner
            picks the communities only of a beta. */}
        {editing && (
          <div className="space-y-2">
            {editing.availability === PluginAvailability.beta ? (
              <>
                <p className="text-sm">{t("pluginServices.reachBeta")}</p>
                <CommunityPicker
                  multiple
                  aria-label={t("pluginServices.betaCommunitiesLabel")}
                  value={form.betaCommunities}
                  onChange={(betaCommunities) => setForm((prev) => ({ ...prev, betaCommunities }))}
                />
                <p className="text-muted-foreground text-xs">
                  {form.betaCommunities.length > 0
                    ? t("pluginServices.betaPickedHelp")
                    : t("pluginServices.betaNoneHelp")}
                </p>
              </>
            ) : (
              <p className="text-sm">
                {editing.availability === PluginAvailability.operations
                  ? t("pluginServices.reachOperations")
                  : t("pluginServices.reachEveryCommunity")}
              </p>
            )}
            <p className="text-muted-foreground text-xs">{t("pluginServices.reachHelp")}</p>
          </div>
        )}

        <div className="flex items-start justify-between gap-3 rounded-md border border-amber-500/50 p-3">
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
      </SettingsSection>

      {footer}
    </form>
  );
};

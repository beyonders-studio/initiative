import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import {
  PluginServiceFormDialog,
  type PluginServiceFormValues,
} from "@/components/platform/PluginServiceFormDialog";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import {
  useCreatePluginService,
  useDeletePluginService,
  usePluginServices,
  useUpdatePluginService,
} from "@/hooks/usePluginServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Label } from "@/ui/label";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Switch } from "@/ui/switch";

/** Whether a registration carries a key set, pasted or by address. */
const hasKeys = (registration: PluginServiceRegistrationRead): boolean =>
  Boolean(registration.jwks_uri) ||
  (registration.jwks !== null && Object.keys(registration.jwks).length > 0);

/**
 * Deployment-level plug-in service registrations (`plugins.manage`).
 *
 * The operator edits a plug-in's deployment facts here: its addresses, keys and
 * reach, and the kill switch. What the plug-in is and may do comes from its
 * listing and is shown read-only.
 */
export const SettingsPluginServicesPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlugins = hasCapability(user, Capability.pluginsManage);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PluginServiceRegistrationRead | null>(null);
  const [disabling, setDisabling] = useState<PluginServiceRegistrationRead | null>(null);
  const [deleting, setDeleting] = useState<PluginServiceRegistrationRead | null>(null);

  const servicesQuery = usePluginServices({ enabled: canManagePlugins });
  const createService = useCreatePluginService();
  const updateService = useUpdatePluginService();
  const deleteService = useDeletePluginService();

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
  };

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (registration: PluginServiceRegistrationRead) => {
    setEditing(registration);
    setDialogOpen(true);
  };

  const handleSubmit = (values: PluginServiceFormValues) => {
    const origins = values.allowedOrigins.length > 0 ? values.allowedOrigins : null;

    if (editing) {
      // A declarative plug-in runs nowhere and signs nothing: it has no address,
      // origins or keys to send.
      const placement =
        editing.kind === "declarative"
          ? {}
          : {
              base_url: values.baseUrl,
              // Always sent, so emptying the field clears it and puts both
              // surfaces back on the base URL.
              page_origin: values.pageOrigin,
              allowed_origins: origins,
              // Null leaves the stored key set alone; {} clears it.
              ...(values.jwks === null ? {} : { jwks: values.jwks }),
              // Always sent, so emptying the field clears the address.
              jwks_uri: values.jwksUri,
            };
      updateService.mutate(
        {
          registrationId: editing.id,
          data: {
            ...placement,
            mandatory: values.mandatory,
            operations_only: values.operationsOnly,
            shared_routes: values.sharedRoutes,
            // Only the values that were typed; a secret left alone is kept.
            ...(Object.keys(values.vendorValues).length > 0
              ? { vendor_values: values.vendorValues }
              : {}),
          },
        },
        {
          onSuccess: () => {
            toast.success(t("pluginServices.saved"));
            closeDialog();
          },
          onError: (error) =>
            toast.error(getErrorMessage(error, "settings:pluginServices.saveError")),
        }
      );
      return;
    }

    createService.mutate(
      {
        public_id: values.publicId,
        base_url: values.baseUrl,
        page_origin: values.pageOrigin || null,
        allowed_origins: origins,
        jwks: values.jwks,
        jwks_uri: values.jwksUri || null,
        mandatory: values.mandatory,
        operations_only: values.operationsOnly,
      },
      {
        onSuccess: () => {
          toast.success(t("pluginServices.created"));
          closeDialog();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:pluginServices.saveError")),
      }
    );
  };

  const setEnabled = (registration: PluginServiceRegistrationRead, enabled: boolean) => {
    updateService.mutate(
      { registrationId: registration.id, data: { enabled } },
      {
        onSuccess: () => {
          setDisabling(null);
          toast.success(
            enabled
              ? t("pluginServices.enabledToast", { name: registration.public_id })
              : t("pluginServices.disabledToast", { name: registration.public_id })
          );
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:pluginServices.toggleError")),
      }
    );
  };

  if (!canManagePlugins) {
    return <p className="text-muted-foreground text-sm">{t("pluginServices.platformOnly")}</p>;
  }
  if (servicesQuery.isLoading) {
    return (
      <SkeletonRegion label={t("pluginServices.loading")}>
        <ListSkeleton rows={3} avatar={false} rowClassName="rounded-lg border bg-card p-4" />
      </SkeletonRegion>
    );
  }
  if (servicesQuery.isError || !servicesQuery.data) {
    return <p className="text-destructive text-sm">{t("pluginServices.loadError")}</p>;
  }

  const registrations = servicesQuery.data;

  return (
    <SettingsSection
      title={t("pluginServices.title")}
      description={t("pluginServices.description")}
      action={
        <Button type="button" onClick={openCreate}>
          {t("pluginServices.addService")}
        </Button>
      }
    >
      {registrations.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("pluginServices.empty")}</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {registrations.map((registration) => {
            const declarative = registration.kind === "declarative";
            const keysMissing = !declarative && !hasKeys(registration);

            return (
              <li key={registration.id} className="space-y-3 px-3 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="rounded bg-muted px-1.5 py-0.5 font-medium text-sm">
                        {registration.public_id}
                      </code>
                      {registration.live ? (
                        <Badge
                          variant="outline"
                          className="border-transparent bg-emerald-600 text-white"
                        >
                          {t("pluginServices.liveBadge")}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-dashed text-muted-foreground">
                          {t("pluginServices.notLiveBadge")}
                        </Badge>
                      )}
                      {!registration.enabled && (
                        <Badge variant="outline" className="border-destructive text-destructive">
                          {t("pluginServices.disabledBadge")}
                        </Badge>
                      )}
                      {!registration.publisher_enabled && (
                        <Badge variant="outline" className="border-destructive text-destructive">
                          {t("pluginServices.publisherDisabledBadge")}
                        </Badge>
                      )}
                      {registration.source === "registry" && (
                        <Badge variant="secondary">{t("pluginServices.registryBadge")}</Badge>
                      )}
                      {registration.operations_only ? (
                        <Badge variant="secondary">
                          {t(
                            registration.mandatory
                              ? "pluginServices.operationsMandatoryBadge"
                              : "pluginServices.operationsOnlyBadge"
                          )}
                        </Badge>
                      ) : (
                        registration.mandatory && (
                          <Badge variant="secondary">{t("pluginServices.mandatoryBadge")}</Badge>
                        )
                      )}
                    </div>
                    {declarative ? (
                      <p className="text-muted-foreground text-sm">
                        {t("pluginServices.declarativeSummary")}
                      </p>
                    ) : registration.base_url ? (
                      <p className="truncate text-muted-foreground text-sm">
                        {registration.base_url}
                      </p>
                    ) : (
                      <p className="text-muted-foreground text-sm">
                        {t("pluginServices.needsAddress")}
                      </p>
                    )}
                    {registration.image_digest && (
                      <p className="break-all text-muted-foreground text-xs">
                        {t("pluginServices.imageSummary", { image: registration.image_digest })}
                      </p>
                    )}
                    {registration.page_origin && (
                      <p className="truncate text-muted-foreground text-sm">
                        {t("pluginServices.pageOriginSummary", {
                          origin: registration.page_origin,
                        })}
                      </p>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <div className="flex items-center gap-2">
                      <Label
                        htmlFor={`plugin-service-enabled-${registration.id}`}
                        className="text-muted-foreground text-xs"
                      >
                        {t("pluginServices.enabledLabel")}
                      </Label>
                      <Switch
                        id={`plugin-service-enabled-${registration.id}`}
                        checked={registration.enabled}
                        disabled={updateService.isPending}
                        onCheckedChange={(checked) => {
                          // Turning it back on is safe; turning it off stops
                          // the plug-in for every community, so that side confirms.
                          if (checked) setEnabled(registration, true);
                          else setDisabling(registration);
                        }}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => openEdit(registration)}
                    >
                      {t("pluginServices.edit")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive"
                      onClick={() => setDeleting(registration)}
                    >
                      {t("pluginServices.delete")}
                    </Button>
                  </div>
                </div>

                <div className="space-y-1 text-muted-foreground text-xs">
                  <p>
                    {t("pluginServices.publisherSummary", { name: registration.publisher_name })}
                    {" · "}
                    {registration.listing_uid ? (
                      <>
                        {t("pluginServices.listingSummary")}{" "}
                        <code className="font-mono">{registration.listing_uid}</code>
                      </>
                    ) : (
                      t("pluginServices.noListing")
                    )}
                  </p>
                  {registration.scope_ceiling.length > 0 && (
                    <p className="break-words">
                      {t("pluginServices.scopeCeilingSummary", {
                        scopes: registration.scope_ceiling.join(", "),
                      })}
                    </p>
                  )}
                  {registration.allowed_origins.length > 0 && (
                    <p className="truncate">
                      {t("pluginServices.allowedOriginsSummary", {
                        origins: registration.allowed_origins.join(", "),
                      })}
                    </p>
                  )}
                  {!registration.enabled && (
                    <p className="text-destructive">{t("pluginServices.disabledHelp")}</p>
                  )}
                  {!registration.publisher_enabled && (
                    <p className="text-destructive">
                      {t("pluginServices.publisherDisabledHelp", {
                        name: registration.publisher_name,
                      })}
                    </p>
                  )}
                  {keysMissing && <p>{t("pluginServices.noKeysHelp")}</p>}
                  {!registration.vendor_ready && <p>{t("pluginServices.vendorMissingHelp")}</p>}
                  {registration.operations_only ? (
                    <p>
                      {t("pluginServices.operationsOnlyHelp")}
                      {registration.mandatory && ` ${t("pluginServices.operationsMandatoryHelp")}`}
                    </p>
                  ) : (
                    registration.mandatory && <p>{t("pluginServices.mandatoryHelp")}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <PluginServiceFormDialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
        editing={editing}
        saving={createService.isPending || updateService.isPending}
        onSubmit={handleSubmit}
      />

      <ConfirmDialog
        open={disabling !== null}
        onOpenChange={(open) => {
          if (!open) setDisabling(null);
        }}
        title={t("pluginServices.disableTitle", { name: disabling?.public_id ?? "" })}
        description={t("pluginServices.disableDescription")}
        confirmLabel={t("pluginServices.disableConfirm")}
        destructive
        isLoading={updateService.isPending}
        onConfirm={() => {
          if (disabling) setEnabled(disabling, false);
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("pluginServices.deleteTitle", { name: deleting?.public_id ?? "" })}
        description={t("pluginServices.deleteDescription")}
        confirmLabel={t("pluginServices.delete")}
        destructive
        confirmationText={deleting?.public_id}
        confirmationLabel={t("pluginServices.deleteConfirmLabel")}
        isLoading={deleteService.isPending}
        onConfirm={() => {
          if (deleting) {
            deleteService.mutate(deleting.id, {
              onSuccess: () => {
                setDeleting(null);
                toast.success(t("pluginServices.deleted"));
              },
              onError: (error) =>
                toast.error(getErrorMessage(error, "settings:pluginServices.deleteError")),
            });
          }
        }}
      />
    </SettingsSection>
  );
};

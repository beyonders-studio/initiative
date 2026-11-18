import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  PluginAvailability,
  type PluginServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import {
  useDeletePluginService,
  usePluginService,
  useUpdatePluginService,
} from "@/hooks/usePluginServices";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { vendorCheckRefusalIn } from "@/lib/pluginServices";
import { localized } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { SettingsPaneSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { PluginServiceAvatar } from "./PluginServiceAvatar";
import { PluginServiceBadges } from "./PluginServiceBadges";
import { PluginServiceForm, type PluginServiceFormValues } from "./PluginServiceForm";
import type { VendorRefusal } from "./VendorClientSection";

/** Whether a registration carries a key set, pasted or by address. */
const hasKeys = (registration: PluginServiceRegistrationRead): boolean =>
  Boolean(registration.jwks_uri) ||
  (registration.jwks !== null && Object.keys(registration.jwks).length > 0);

/**
 * One plug-in service (`plugins.manage`): what its listing says it is, what
 * keeps it from being live, and the deployment facts the operator gives it.
 * Suspending it and deleting it are here too, each confirmed.
 */
export const PluginServicePage = () => {
  const { t, i18n } = useTranslation("settings");
  const { user } = useAuth();
  const navigate = useNavigate();
  const canManagePlugins = hasCapability(user, Capability.pluginsManage);
  const { registrationId } = useParams({ strict: false }) as { registrationId?: string };
  const id = Number(registrationId);
  const valid = Number.isInteger(id) && id > 0;

  const query = usePluginService(id, { enabled: canManagePlugins && valid });
  const updateService = useUpdatePluginService();
  const deleteService = useDeletePluginService();
  // Bumped by each save, so the form remounts on the values just saved.
  const [saves, setSaves] = useState(0);
  const [confirming, setConfirming] = useState<"suspend" | "delete" | null>(null);
  // What the plug-in's vendor check refused the last save for, shown on the
  // fields it blames until a save goes through.
  const [refusal, setRefusal] = useState<VendorRefusal | null>(null);

  const back = (
    <Button asChild variant="ghost" size="sm" className="-ml-2">
      <Link to="/settings/platform/integrations">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {t("pluginServices.back")}
      </Link>
    </Button>
  );

  if (!canManagePlugins) {
    return <p className="text-muted-foreground text-sm">{t("pluginServices.platformOnly")}</p>;
  }
  if (query.isLoading) {
    return (
      <SkeletonRegion>
        <SettingsPaneSkeleton />
      </SkeletonRegion>
    );
  }
  if (!valid || query.isError || !query.data) {
    return (
      <div className="space-y-4">
        {back}
        <StatusMessage onRetry={valid ? query.refetch : undefined} />
      </div>
    );
  }

  const registration = query.data;
  const declarative = registration.kind === "declarative";

  const handleSubmit = (values: PluginServiceFormValues) => {
    // A declarative plug-in runs nowhere and signs nothing: it has no address,
    // origins or keys to send.
    const placement = declarative
      ? {}
      : {
          base_url: values.baseUrl,
          // Always sent, so emptying the field clears it and puts both
          // surfaces back on the base URL.
          page_origin: values.pageOrigin,
          allowed_origins: values.allowedOrigins.length > 0 ? values.allowedOrigins : null,
          // Null leaves the stored key set alone; {} clears it.
          ...(values.jwks === null ? {} : { jwks: values.jwks }),
          // Always sent, so emptying the field clears the address.
          jwks_uri: values.jwksUri,
        };
    updateService.mutate(
      {
        registrationId: registration.id,
        data: {
          ...placement,
          mandatory: values.mandatory,
          shared_routes: values.sharedRoutes,
          // The whole list, replacing the one stored; only a beta has one.
          ...(registration.availability === PluginAvailability.beta
            ? { beta_community_ids: values.betaCommunities.map((community) => community.id) }
            : {}),
          // Only the values that were typed; a secret left alone is kept.
          ...(Object.keys(values.vendorValues).length > 0
            ? { vendor_values: values.vendorValues }
            : {}),
        },
      },
      {
        onSuccess: (saved) => {
          setRefusal(null);
          toast.success(t("pluginServices.saved"));
          if (saved.vendor_check === "not_run") {
            toast.warning(t("pluginServices.vendorCheckNotRun"));
          }
          setSaves((count) => count + 1);
        },
        onError: (error) => {
          const refused = vendorCheckRefusalIn(error);
          const text =
            (refused && localized(refused.message, i18n.language)) ||
            getErrorMessage(error, "settings:pluginServices.saveError");
          setRefusal(refused ? { fields: refused.fields, text, shows: refused.shows } : null);
          toast.error(text);
        },
      }
    );
  };

  const setSuspended = (suspended: boolean) => {
    updateService.mutate(
      { registrationId: registration.id, data: { suspended } },
      {
        onSuccess: () => {
          setConfirming(null);
          toast.success(
            suspended
              ? t("pluginServices.suspendedToast", { name: registration.public_id })
              : t("pluginServices.liftedToast", { name: registration.public_id })
          );
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:pluginServices.suspensionError")),
      }
    );
  };

  // What keeps it from being live, or what it does that is out of the
  // ordinary, one sentence each.
  const notes = [
    registration.suspended_at != null && {
      text: t("pluginServices.suspendedHelp"),
      destructive: true,
    },
    !registration.publisher_enabled && {
      text: t("pluginServices.publisherDisabledHelp", { name: registration.publisher_name }),
      destructive: true,
    },
    !declarative && !registration.base_url && { text: t("pluginServices.needsAddress") },
    !declarative && !hasKeys(registration) && { text: t("pluginServices.noKeysHelp") },
    !registration.vendor_ready && { text: t("pluginServices.vendorMissingHelp") },
    registration.availability === PluginAvailability.operations && {
      text: registration.mandatory
        ? `${t("pluginServices.operationsOnlyHelp")} ${t("pluginServices.operationsMandatoryHelp")}`
        : t("pluginServices.operationsOnlyHelp"),
    },
  ].filter((note): note is { text: string; destructive?: boolean } => Boolean(note));

  const facts = [
    { label: t("pluginServices.factPublisher"), value: registration.publisher_name },
    {
      label: t("pluginServices.factVersion"),
      value: registration.version ?? t("pluginServices.noListing"),
    },
    registration.listing_uid && {
      label: t("pluginServices.factListing"),
      value: registration.listing_uid,
      mono: true,
    },
    registration.image_digest && {
      label: t("pluginServices.factImage"),
      value: registration.image_digest,
      mono: true,
    },
    registration.scope_ceiling.length > 0 && {
      label: t("pluginServices.factScopes"),
      value: registration.scope_ceiling.join(", "),
    },
  ].filter((fact): fact is { label: string; value: string; mono?: boolean } => Boolean(fact));

  return (
    <div className="space-y-6">
      {back}

      <header className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-4">
            <PluginServiceAvatar registration={registration} className="size-14" />
            <div className="min-w-0 space-y-2">
              <div>
                <h2 className="break-all font-semibold text-xl">
                  {registration.name ?? registration.public_id}
                </h2>
                {registration.name && (
                  <p className="break-all font-mono text-muted-foreground text-sm">
                    {registration.public_id}
                  </p>
                )}
              </div>
              <PluginServiceBadges registration={registration} />
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {/* Lifting is safe; suspending cuts the plug-in off in every
                community, so that side confirms. */}
            {registration.suspended_at != null ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={updateService.isPending}
                onClick={() => setSuspended(false)}
              >
                {t("pluginServices.lift")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-destructive"
                disabled={updateService.isPending}
                onClick={() => setConfirming("suspend")}
              >
                {t("pluginServices.suspend")}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-destructive"
              onClick={() => setConfirming("delete")}
            >
              {t("pluginServices.delete")}
            </Button>
          </div>
        </div>

        <dl className="grid grid-cols-fill-48/4 gap-x-6 gap-y-3">
          {facts.map((fact) => (
            <div key={fact.label} className="min-w-0 space-y-0.5">
              <dt className="text-muted-foreground text-xs">{fact.label}</dt>
              <dd className={fact.mono ? "break-all font-mono text-sm" : "break-words text-sm"}>
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>

        {notes.length > 0 && (
          <ul className="space-y-1 text-sm">
            {notes.map((note) => (
              <li
                key={note.text}
                className={note.destructive ? "text-destructive" : "text-muted-foreground"}
              >
                {note.text}
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground text-sm">{t("pluginServices.editDescription")}</p>
      </header>

      <PluginServiceForm
        key={saves}
        editing={registration}
        onSubmit={handleSubmit}
        vendorRefusal={refusal}
        footer={
          <div className="flex justify-end">
            <Button type="submit" disabled={updateService.isPending}>
              {updateService.isPending ? t("pluginServices.saving") : t("pluginServices.save")}
            </Button>
          </div>
        }
      />

      <ConfirmDialog
        open={confirming === "suspend"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={t("pluginServices.suspendTitle", { name: registration.public_id })}
        description={t("pluginServices.suspendDescription")}
        confirmLabel={t("pluginServices.suspend")}
        destructive
        isLoading={updateService.isPending}
        onConfirm={() => setSuspended(true)}
      />

      <ConfirmDialog
        open={confirming === "delete"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={t("pluginServices.deleteTitle", { name: registration.public_id })}
        description={t("pluginServices.deleteDescription")}
        confirmLabel={t("pluginServices.delete")}
        destructive
        confirmationText={registration.public_id}
        confirmationLabel={t("pluginServices.deleteConfirmLabel")}
        isLoading={deleteService.isPending}
        onConfirm={() =>
          deleteService.mutate(registration.id, {
            onSuccess: () => {
              toast.success(t("pluginServices.deleted"));
              void navigate({ to: "/settings/platform/integrations", replace: true });
            },
          })
        }
      />
    </div>
  );
};

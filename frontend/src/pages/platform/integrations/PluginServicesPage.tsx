import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useCreatePluginService, usePluginServices } from "@/hooks/usePluginServices";
import { useServerTableState } from "@/hooks/useServerTableState";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { DataTable } from "@/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import type { AppColumnDef } from "@/ui/lib/table";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { PluginServiceAvatar } from "./PluginServiceAvatar";
import { PluginServiceBadges } from "./PluginServiceBadges";
import { PluginServiceForm, type PluginServiceFormValues } from "./PluginServiceForm";

/**
 * Deployment-level plug-in service registrations (`plugins.manage`).
 *
 * A deployment may run any number of plug-ins, so the list is searched and paged
 * on the server and each row is one line: the plug-in, its version, and its
 * state. A plug-in's addresses, keys, vendor client and reach are edited on its
 * own page (`PluginServicePage`).
 */
export const PluginServicesPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const navigate = useNavigate();
  const canManagePlugins = hasCapability(user, Capability.pluginsManage);
  const [adding, setAdding] = useState(false);

  const table = useServerTableState();
  const servicesQuery = usePluginServices(table.params, { enabled: canManagePlugins });
  const createService = useCreatePluginService();

  const handleCreate = (values: PluginServiceFormValues) => {
    createService.mutate(
      {
        public_id: values.publicId,
        base_url: values.baseUrl,
        page_origin: values.pageOrigin || null,
        allowed_origins: values.allowedOrigins.length > 0 ? values.allowedOrigins : null,
        jwks: values.jwks,
        jwks_uri: values.jwksUri || null,
        mandatory: values.mandatory,
      },
      {
        onSuccess: (registration) => {
          toast.success(t("pluginServices.created"));
          setAdding(false);
          void navigate({
            to: "/settings/platform/integrations/plugins/$registrationId",
            params: { registrationId: String(registration.id) },
          });
        },
      }
    );
  };

  const columns: AppColumnDef<PluginServiceRegistrationRead>[] = [
    {
      accessorKey: "public_id",
      header: t("pluginServices.columns.plugin"),
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex min-w-0 items-center gap-3">
          <PluginServiceAvatar registration={row.original} className="size-9" />
          <div className="min-w-0">
            <Link
              to="/settings/platform/integrations/plugins/$registrationId"
              params={{ registrationId: String(row.original.id) }}
              className="break-all font-medium text-sm hover:underline"
            >
              {row.original.name ?? row.original.public_id}
            </Link>
            <p className="break-all text-muted-foreground text-xs">
              {/* The identifier under the name; alone, it is the title. */}
              {row.original.name ? (
                <span className="font-mono">{row.original.public_id} · </span>
              ) : null}
              {row.original.publisher_name}
            </p>
          </div>
        </div>
      ),
    },
    {
      id: "version",
      header: t("pluginServices.columns.version"),
      enableSorting: false,
      cell: ({ row }) =>
        row.original.version ? (
          <span className="font-mono text-sm tabular-nums">{row.original.version}</span>
        ) : (
          <span className="text-muted-foreground text-sm">{t("pluginServices.noListing")}</span>
        ),
    },
    {
      id: "status",
      header: t("pluginServices.columns.status"),
      enableSorting: false,
      cell: ({ row }) => <PluginServiceBadges registration={row.original} />,
    },
  ];

  if (!canManagePlugins) {
    return <p className="text-muted-foreground text-sm">{t("pluginServices.platformOnly")}</p>;
  }
  if (servicesQuery.isLoading) {
    return (
      <SkeletonRegion>
        <TableSkeleton rows={6} columns={3} />
      </SkeletonRegion>
    );
  }
  if (servicesQuery.isError || !servicesQuery.data) {
    return <StatusMessage onRetry={servicesQuery.refetch} />;
  }

  const page = servicesQuery.data;
  // Empty with nothing searched: none at all, rather than none that match.
  const none = page.total_count === 0 && !table.params.search;

  return (
    <SettingsSection
      title={t("pluginServices.title")}
      description={t("pluginServices.description")}
      action={
        <Button type="button" onClick={() => setAdding(true)}>
          {t("pluginServices.addService")}
        </Button>
      }
    >
      {none ? (
        <p className="text-muted-foreground text-sm">{t("pluginServices.empty")}</p>
      ) : (
        <DataTable
          columns={columns}
          data={page.items}
          getRowId={(registration) => String(registration.id)}
          enableFilterInput
          filterInputPlaceholder={t("pluginServices.filterPlaceholder")}
          enablePagination
          {...table.tableProps(page.total_count, page.page)}
        />
      )}

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("pluginServices.createTitle")}</DialogTitle>
            <DialogDescription>{t("pluginServices.createDescription")}</DialogDescription>
          </DialogHeader>
          <PluginServiceForm
            editing={null}
            plain
            onSubmit={handleCreate}
            footer={
              <DialogFooter
                submitLabel={t("pluginServices.save")}
                pendingLabel={t("pluginServices.saving")}
                pending={createService.isPending}
              />
            }
          />
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
};

/**
 * THE settings frame every tool gets.
 *
 * Rename, describe, tag, share, and delete are identical for all six tools, so
 * they live here once. Everything the frame needs is derived from the `tool`
 * value — breadcrumb labels, section routes, the tag mutation — and all of its
 * copy comes from the shared `common:toolSettings.*` namespace. Every tool
 * mounts it through `ToolSettingsPage`, over its `TOOL_HOOKS`.
 *
 * The sections are real routes — `/settings/access` is a place, not a piece of
 * component state — so sharing can be linked to, and the back button walks
 * back through the sections that were visited. The bar still looks and behaves
 * like tabs; selecting one navigates.
 *
 * A tool with genuinely extra settings passes cards as `detailsExtra`, or
 * names a whole extra section in `extraTabs` and serves it from a route beside
 * the shared ones; the shell stays the same shape for every tool.
 */

import { Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema, Tool } from "@/api/generated/initiativeAPI.schemas";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { INSTANCE_LAYOUT_TOOLS, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute, toolSettingsSectionRoute } from "@/lib/tools";
import { SettingsPaneSkeleton } from "@/ui/page-skeletons";

import { canUseArchiveCard } from "./ToolArchiveCard";
import { canUseDuplicateCard } from "./ToolDuplicateCard";
import {
  type ToolExportOptions,
  type ToolMutation,
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "./ToolSettingsContext";

export type { ToolMutation, ToolSettingsEntity };

export interface ToolSettingsLayoutProps {
  tool: Tool;
  entity: ToolSettingsEntity | undefined;
  isLoading: boolean;
  isError: boolean;
  /**
   * The rename/describe mutation. Omit it to drop the built-in details form —
   * a file's name is edited in the editor.
   */
  update?: ToolMutation<{ name?: string; description?: string | null }>;
  /** Marks it a template or takes it back — projects and files. */
  template?: ToolMutation<{ is_template: boolean }>;
  setGrants: ToolMutation<ResourceGrantSchema[]>;
  remove: ToolMutation<number>;
  /** Extra cards for the Details section, e.g. a calendar's color. */
  detailsExtra?: ReactNode;
  /** Extra fields inside the Details card itself, below the description. Each
   *  saves on its own; the card's Save button is for the name and description. */
  detailsInline?: ReactNode;
  /**
   * Overrides for the export card the Advanced section gives every tool — only
   * for a tool whose formats depend on the entity.
   */
  exportOptions?: ToolExportOptions;
  /**
   * Whole extra sections, for settings too large to sit in a card (project
   * task statuses). Each `value` is the route segment serving it, so a tab
   * named here needs a route file beside the shared sections.
   */
  extraTabs?: { value: string; label: string }[];
}

export const ToolSettingsLayout = ({
  tool,
  entity,
  isLoading,
  isError,
  update,
  template,
  setGrants,
  remove,
  detailsExtra,
  detailsInline,
  exportOptions,
  extraTabs = [],
}: ToolSettingsLayoutProps) => {
  const { t } = useTranslation(["common", "nav", "access", "layouts"]);
  const gp = useCommunityPath();
  // A tool that lays out its own items offers its layouts to whoever may
  // change them; the server says who on the set.
  const layouts = useInstanceLayouts(
    tool,
    INSTANCE_LAYOUT_TOOLS.has(tool) ? (entity?.id ?? null) : null
  ).data;

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  if (isError || !entity) {
    return <p className="text-destructive">{t("common:toolSettings.notFound")}</p>;
  }

  const sectionPath = (section: string) =>
    gp(toolSettingsSectionRoute(tool, entity.initiative_id, entity.id, section));

  const tabs = [
    { value: "details", label: t("common:toolSettings.tabDetails"), path: sectionPath("details") },
    // Whoever may edit it sees who it is shared with; only the owner changes
    // that, which the section asks itself.
    {
      value: "access",
      label: t("common:toolSettings.tabAccess"),
      path: sectionPath("access"),
      visible: entity.can.edit,
    },
    {
      value: "layouts",
      label: t("layouts:tab"),
      path: sectionPath("layouts"),
      visible: Boolean(layouts?.can_configure),
    },
    ...extraTabs.map((tab) => ({
      value: tab.value,
      label: tab.label,
      path: sectionPath(tab.value),
    })),
    // Advanced holds a tool's own extra operations, duplicating, archiving,
    // exporting and deletion, so it is offered only when this entity has one
    // of them to offer.
    {
      value: "advanced",
      label: t("common:toolSettings.tabAdvanced"),
      path: sectionPath("advanced"),
      visible:
        entity.can.export ||
        entity.can.delete ||
        canUseArchiveCard(entity) ||
        canUseDuplicateCard(tool, entity),
    },
  ];

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={tool}
        initiativeId={entity.initiative_id}
        trail={[{ label: entity.name, to: toolDetailRoute(tool, entity.initiative_id, entity.id) }]}
        title={t("common:toolSettings.title")}
      />

      <SettingsTabsNav tabs={tabs} />

      <ToolSettingsProvider
        value={{
          tool,
          entity,
          update,
          template,
          setGrants,
          remove,
          detailsExtra,
          detailsInline,
          exportOptions,
        }}
      >
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </ToolSettingsProvider>
    </div>
  );
};

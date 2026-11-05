/**
 * What a tool's settings sections read.
 *
 * The sections are routes now, so the tool wrapper that fetches the entity no
 * longer hands them props — it renders {@link ToolSettingsLayout}, which puts
 * the loaded entity, its mutations, and the tool's extra cards here for
 * whichever section the address names to pick up.
 */

import { createContext, type ReactNode, useContext } from "react";

import type {
  OwnerPluginSummary,
  PropertySummary,
  ResourceGrantSchema,
  TagSummary,
  Tool,
  ToolCan,
} from "@/api/generated/initiativeAPI.schemas";
import type { ExportExtraAction, ExportFormatOption } from "@/components/exports/ExportButton";
import type { ExportContentSeed } from "@/components/exports/ExportWizard";

/**
 * The slice of a tool's read schema its settings need. Every tool — counter
 * groups, calendars, dashboards, projects, and files — satisfies it as-is.
 */
export interface ToolSettingsEntity {
  id: number;
  name: string;
  description?: string | null;
  initiative_id: number | null;
  tags: TagSummary[];
  properties?: PropertySummary[];
  grants: ResourceGrantSchema[];
  comments_enabled: boolean;
  /** When this was archived, or null while it is live. */
  archived_at: string | null;
  /** What this viewer may do to it, as the server answers it. */
  can: ToolCan;
  /** Projects and files only: a template, which read is enough to copy. */
  is_template?: boolean;
  /**
   * The installed plug-in that owns it, where the tool's read model names one
   * (projects and files). Elsewhere the sharing control finds the plug-in
   * from the owner grant.
   */
  owner_plugin?: OwnerPluginSummary | null;
}

/**
 * What a tool's export card offers when the tool's registry formats are not
 * the whole answer — a file's formats follow its type, a whiteboard adds
 * pictures only the browser can draw, and a project starts from the
 * exporting person's view of its tasks.
 */
export interface ToolExportOptions {
  formats?: ExportFormatOption[];
  extraActions?: ExportExtraAction[];
  /** The exporting person's own view of its content, which the export
   *  starts from: a project's task filters and order. */
  content?: ExportContentSeed;
}

/** Per-call callbacks so the sections — not each wrapper — own toasts and routing. */
export type ToolSettingsMutateOptions = { onSuccess?: () => void; onError?: () => void };

export interface ToolMutation<TVars> {
  mutate: (vars: TVars, options?: ToolSettingsMutateOptions) => void;
  isPending: boolean;
}

export interface ToolSettingsContextValue {
  tool: Tool;
  /** Always loaded: the layout renders no section until the entity is in hand. */
  entity: ToolSettingsEntity;
  /**
   * The rename/describe mutation. Absent for a file, whose name is edited
   * in the editor.
   */
  update?: ToolMutation<{ name?: string; description?: string | null }>;
  /** Marks it a template or takes it back. Only tools with templates pass it. */
  template?: ToolMutation<{ is_template: boolean }>;
  setGrants: ToolMutation<ResourceGrantSchema[]>;
  remove: ToolMutation<number>;
  /** Extra cards for the Details section, e.g. a calendar's color. */
  detailsExtra?: ReactNode;
  /** Extra fields inside the Details card itself, below the description. Each
   *  saves on its own; the card's Save button is for the name and description. */
  detailsInline?: ReactNode;
  /** Extra cards for the Advanced section, e.g. duplicate or archive. */
  advancedExtra?: ReactNode;
  /** Overrides for the Advanced section's export card. */
  exportOptions?: ToolExportOptions;
}

const ToolSettingsContext = createContext<ToolSettingsContextValue | null>(null);

export const ToolSettingsProvider = ToolSettingsContext.Provider;

/** The entity and mutations the surrounding {@link ToolSettingsLayout} loaded. */
export const useToolSettings = (): ToolSettingsContextValue => {
  const value = useContext(ToolSettingsContext);
  if (!value) {
    throw new Error("useToolSettings must be used within a tool settings route");
  }
  return value;
};

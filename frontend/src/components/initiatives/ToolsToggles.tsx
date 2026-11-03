import { Check, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIconTile, ToolSketch } from "@/components/initiatives/ToolSkeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DEFAULT_ENABLED_TOOLS,
  SIDEBAR_TOOLS,
  toolCamelPlural,
  toolRouteSegment,
  toolViewPermission,
} from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * The roles that can actually see a tool once its master switch is on.
 *
 * Manager roles see every tool whatever their stored permissions say, so they
 * are always in the list; every other role is in it only if its
 * `{plural}_enabled` permission is on. Exported because it is the fact the
 * whole screen turns on — a tool with no non-manager role behind it is on for
 * the manager reading the screen and off for everybody else.
 */
export const rolesThatCanView = (
  roles: InitiativeRoleRead[],
  tool: Tool
): { granted: InitiativeRoleRead[]; nonManagerGranted: InitiativeRoleRead[] } => {
  const key = toolViewPermission(tool);
  const granted = roles.filter((role) => role.is_manager || (role.permissions[key] ?? false));
  return { granted, nonManagerGranted: granted.filter((role) => !role.is_manager) };
};

export interface ToolsSectionProps {
  /** Current master-switch value per tool. */
  values: Record<Tool, boolean> | Partial<Record<Tool, boolean>>;
  /** Toggle one tool's master switch. */
  onToggle: (tool: Tool, value: boolean) => void;
  canManage: boolean;
  isSaving: boolean;
  /** "card" wraps the rows in a Card with title+description (settings page). "plain" returns just the rows (for use inside an Accordion). */
  layout?: "card" | "plain";
  /** Optional prefix for input IDs so multiple instances don't collide. */
  idPrefix?: string;
  /**
   * The initiative's roles. When present, an enabled tool says who can see it —
   * absent on the create-initiative dialog, where no roles exist yet.
   */
  roles?: InitiativeRoleRead[];
  /** Open the roles screen. Rendered as a link beside the audience line. */
  onManageRoles?: () => void;
  /** Grant a tool's view permission to every non-manager role, in one step. */
  onGrantToEveryone?: (tool: Tool) => void;
  /** The switches the community set for every initiative: shown, not changed. */
  setByCommunity?: Partial<Record<Tool, boolean>>;
}

interface ToolPickerCardProps {
  tool: Tool;
  id: string;
  title: string;
  description: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled: boolean;
  /** Rendered under the card, OUTSIDE the toggle. The audience line carries
   *  its own buttons, and a button inside a button is invalid HTML. */
  audience?: ReactNode;
}

/**
 * One tool, as something you can look at rather than a row with a switch.
 *
 * The sketch is the point: "queue" and "counter" mean nothing to somebody who
 * has not seen one, and this card is where both the create wizard and the
 * settings screen ask them to decide. Same card in both places, so the picture
 * somebody learned the tool from is the picture they see again later.
 */
export const ToolPickerCard = ({
  tool,
  id,
  title,
  description,
  checked,
  onCheckedChange,
  disabled,
  audience,
}: ToolPickerCardProps) => (
  <div
    data-slot="tool-card"
    className={cn(
      "flex flex-col gap-2 rounded-lg border p-3 transition-colors",
      checked ? "border-primary bg-primary/5" : "hover:bg-accent"
    )}
  >
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      id={id}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex flex-col gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60",
        checked ? "text-foreground" : "text-muted-foreground"
      )}
    >
      <span className="flex items-center gap-2">
        <ToolIconTile tool={tool} active={checked} />
        <span className="flex-1 font-medium text-sm">{title}</span>
        <span
          aria-hidden="true"
          className={cn(
            "flex h-5 w-5 items-center justify-center rounded-full border",
            checked ? "border-primary bg-primary text-primary-foreground" : "border-border"
          )}
        >
          {checked ? <Check className="h-3 w-3" /> : null}
        </span>
      </span>
      <ToolSketch tool={tool} active={checked} />
      <span className="text-xs leading-snug">{description}</span>
    </button>
    {audience}
  </div>
);

/**
 * Who can see this tool now that it is on — the half of the answer the master
 * switch alone never gave. A tool no ordinary role has been granted is on for
 * managers only, which is the state the switch used to leave behind silently,
 * so that case says so and offers the one-click grant.
 */
const ToolAudience = ({
  tool,
  roles,
  onManageRoles,
  onGrantToEveryone,
  disabled,
}: {
  tool: Tool;
  roles: InitiativeRoleRead[];
  onManageRoles?: () => void;
  onGrantToEveryone?: (tool: Tool) => void;
  disabled: boolean;
}) => {
  const { t } = useTranslation("initiatives");
  const { nonManagerGranted } = rolesThatCanView(roles, tool);
  const managersOnly = nonManagerGranted.length === 0;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-2 text-xs">
      {managersOnly ? (
        <span className="flex items-center gap-1.5 text-amber-600 dark:text-amber-500">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" />
          {t("settings.toolAudience.managersOnly")}
        </span>
      ) : (
        <span className="text-muted-foreground">
          {t("settings.toolAudience.visibleTo", {
            roles: nonManagerGranted.map((role) => role.display_name).join(", "),
          })}
        </span>
      )}
      {managersOnly && onGrantToEveryone && (
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          disabled={disabled}
          onClick={() => onGrantToEveryone(tool)}
        >
          {t("settings.toolAudience.grantToEveryone")}
        </Button>
      )}
      {onManageRoles && (
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-muted-foreground text-xs"
          onClick={onManageRoles}
        >
          {t("settings.toolAudience.manageRoles")}
        </Button>
      )}
    </div>
  );
};

/**
 * The tool grid, derived from the registry — projects and files included.
 * They were exempt when everything else hung off them; relationships ended
 * that, so they are cards here like the rest and differ only in starting on.
 *
 * Pass `roles` and each enabled card gains its audience line; omit it (the
 * create wizard, where no roles exist yet) and it does not.
 */
export const ToolsSection = ({
  values,
  onToggle,
  canManage,
  isSaving,
  layout = "card",
  idPrefix = "tools",
  roles,
  onManageRoles,
  onGrantToEveryone,
  setByCommunity = {},
}: ToolsSectionProps) => {
  const { t } = useTranslation("initiatives");
  const disabled = !canManage || isSaving;

  const rows = (
    // Sized to the space it is in, not to the viewport: this grid renders
    // both inside a dialog and across a full settings page, and a viewport
    // breakpoint would give the narrow one three columns on a wide screen.
    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(13rem,100%),1fr))] gap-3">
      {SIDEBAR_TOOLS.map((tool) => {
        const camel = toolCamelPlural(tool);
        // Unset means the tool's own default, not off — projects and files
        // are in this list now and start on.
        const enabled = values[tool] ?? DEFAULT_ENABLED_TOOLS.has(tool);
        const fixed = tool in setByCommunity;
        return (
          <ToolPickerCard
            key={tool}
            tool={tool}
            id={`${idPrefix}-${toolRouteSegment(tool)}-toggle`}
            title={t(`${camel}Feature` as never)}
            description={t(`${camel}FeatureDescription` as never)}
            checked={enabled}
            onCheckedChange={(value) => onToggle(tool, value)}
            disabled={disabled || fixed}
            audience={
              fixed ? (
                <p className="border-t pt-2 text-muted-foreground text-xs">
                  {t("settings.setByCommunity")}
                </p>
              ) : enabled && roles ? (
                <ToolAudience
                  tool={tool}
                  roles={roles}
                  onManageRoles={onManageRoles}
                  onGrantToEveryone={onGrantToEveryone}
                  disabled={disabled}
                />
              ) : undefined
            }
          />
        );
      })}
    </div>
  );

  if (layout === "plain") return rows;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{t("advancedTools")}</CardTitle>
        <CardDescription>{t("advancedToolsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>{rows}</CardContent>
    </Card>
  );
};

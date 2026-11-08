/**
 * THE breadcrumb trail for every tool surface: Initiative → tool list →
 * whatever sits above the page (a task's project, a setting's entity). It
 * names where the page lives, never the page itself — the page's own title
 * says that, right below it. The initiative and tool-list crumbs are derived
 * from the `Tool` enum via `src/lib/tools.ts`, so a new tool's pages get the
 * right shape for free.
 */
import { Link } from "@tanstack/react-router";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useListedInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { initiativeRoute, toolListRoute, toolNavLabelKey } from "@/lib/tools";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbSeparator,
} from "@/ui/breadcrumb";

export interface ToolBreadcrumbSegment {
  label: ReactNode;
  /** Community-relative path (e.g. from `toolDetailRoute`). */
  to: string;
}

export interface ToolBreadcrumbProps {
  tool: Tool;
  /** The initiative this entity lives in. Omit (or null) for a community-level
   *  entity (e.g. a calendar with no initiative) — that crumb is dropped. */
  initiativeId?: number | null;
  /** Ancestors after the tool-list crumb, in order: a task's project, the
   *  entity a settings page belongs to. */
  trail?: ToolBreadcrumbSegment[];
}

export const ToolBreadcrumb = ({ tool, initiativeId, trail = [] }: ToolBreadcrumbProps) => {
  const { t } = useTranslation("nav");
  const gp = useCommunityPath();
  const initiativeName = useListedInitiative(initiativeId)?.name;
  // A community-level entity (only calendars have any) belongs to no initiative, so
  // there is no tool tab to go back to — its crumb reads as plain text.
  const hasInitiative = initiativeId != null;

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {initiativeName && (
          <>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={gp(initiativeRoute(initiativeId as number))}>{initiativeName}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
          </>
        )}
        <BreadcrumbItem>
          {hasInitiative ? (
            <BreadcrumbLink asChild>
              <Link to={gp(toolListRoute(tool, initiativeId as number))}>
                {t(toolNavLabelKey(tool))}
              </Link>
            </BreadcrumbLink>
          ) : (
            t(toolNavLabelKey(tool))
          )}
        </BreadcrumbItem>
        {trail.map((segment, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: trail is a fixed, caller-provided sequence — position is the identity
          <Fragment key={index}>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={gp(segment.to)}>{segment.label}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
};

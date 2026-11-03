/**
 * One table row, in terms every tool can answer — and the one place a tool's
 * list response is turned into one.
 *
 * Two pages read the same table: a community's front page, showing one tool
 * across that community, and My Tools, showing one tool across every community
 * the reader belongs to. The rows are the same rows either way, so the mapping
 * lives here rather than in each page's hook: a new `Tool` member fails to
 * build in the `switch` below until it can produce them, and it then appears on
 * both pages at once.
 */

import type { TFunction } from "i18next";
import type { ReactNode } from "react";

import type {
  CalendarListResponse,
  CounterGroupListResponse,
  DashboardListResponse,
  FileListResponse,
  PostListResponse,
  ProjectListResponse,
  QueueListResponse,
  TagSummary,
  WikiListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { TOOLS, toolDetailRoute } from "@/lib/tools";

/** One row of a tool table, in terms every tool can answer. */
export interface ToolRow {
  id: number;
  /** Which community the row lives in — what makes its address absolute. */
  communityId: number;
  name: string;
  /** Community-relative detail route, e.g. `/projects/12`. */
  href: string;
  /** Leading mark in the name cell — a project's emoji, a calendar's colour. */
  glyph: ReactNode;
  /** `null` for the community-level rows a tool allows (calendars). */
  initiativeId: number | null;
  tags: TagSummary[];
  updatedAt: string;
  /** The tool's own column: what this row is, in its own terms. Left out
   *  for a tool without one ({@link TOOL_HAS_DETAIL}). Text here is read for
   *  the people it mentions, which a post's opening or a calendar's
   *  description can hold. */
  detail?: ReactNode;
}

/**
 * Whether a tool's table has a column of its own ({@link ToolRow.detail}).
 * Stated for every tool, so a new one has to say.
 */
export const TOOL_HAS_DETAIL: Record<Tool, boolean> = {
  [Tool.project]: true,
  [Tool.file]: true,
  [Tool.queue]: false,
  [Tool.counter_group]: false,
  [Tool.calendar]: true,
  [Tool.dashboard]: true,
  [Tool.post]: true,
  [Tool.wiki]: false,
};

/**
 * A page of each tool's list, however the caller fetched it. Exactly one is
 * ever populated — the tool the table is showing — but the shape is stated for
 * every tool so the mapping below can be exhaustive over `Tool`.
 *
 * Every key is REQUIRED (and `undefined` is a legal value) so a caller
 * assembling one must name every tool. Optional keys let a new tool ship with
 * its entry simply missing: the table then asked for posts, got a response,
 * mapped it through a map that never mentioned them, and rendered "No results"
 * with nothing wrong anywhere the compiler could see.
 */
export type ToolResponses = {
  [Tool.project]: ProjectListResponse | undefined;
  [Tool.file]: FileListResponse | undefined;
  [Tool.queue]: QueueListResponse | undefined;
  [Tool.counter_group]: CounterGroupListResponse | undefined;
  [Tool.calendar]: CalendarListResponse | undefined;
  [Tool.dashboard]: DashboardListResponse | undefined;
  [Tool.post]: PostListResponse | undefined;
  [Tool.wiki]: WikiListResponse | undefined;
};

/**
 * A {@link ToolResponses} holding one tool's page and nothing else.
 *
 * Both tables show one tool at a time and gate every other query off, so this
 * is exactly what they have in hand. The keys come from the registry rather
 * than a literal, which keeps the "name every tool" promise above without a
 * second list to keep in step — `Object.fromEntries` is what loses the key
 * union on the way, hence the assertion.
 */
export const oneToolResponse = <T extends Tool>(tool: T, page: ToolResponses[T]): ToolResponses => {
  const responses = Object.fromEntries(
    TOOLS.map((candidate) => [candidate, undefined])
  ) as ToolResponses;
  responses[tool] = page;
  return responses;
};

const ColourDot = ({ colour }: { colour: string }) => (
  <span
    aria-hidden
    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
    style={{ backgroundColor: colour }}
  />
);

/**
 * Turn one tool's page of results into table rows.
 *
 * `fallbackCommunityId` answers for a row whose payload leaves the community
 * unsaid — the community-scoped lists, where every row is in the community the
 * page is already showing.
 */
export function buildToolRows(
  tool: Tool,
  data: ToolResponses,
  t: TFunction<"communityHome">,
  fallbackCommunityId: number
): ToolRow[] {
  // Each row addresses its own initiative — a table spanning them (and, on My
  // Tools, spanning communities) needs the whole chain, not just the id.
  const href = (id: number, initiativeId: number | null) => toolDetailRoute(tool, initiativeId, id);

  switch (tool) {
    case Tool.project:
      return (data[Tool.project]?.items ?? []).map((project) => {
        const { completed, total } = project.task_summary;
        const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
        return {
          id: project.id,
          communityId: project.community_id ?? fallbackCommunityId,
          name: project.name,
          href: href(project.id, project.initiative_id),
          glyph: project.icon,
          initiativeId: project.initiative_id,
          tags: project.tags,
          updatedAt: project.updated_at,
          detail: (
            <span className="flex items-center gap-2">
              <ProgressCircle value={percent} className="h-6 w-6 shrink-0" />
              {t("detail.tasksDone", { completed, total })}
            </span>
          ),
        };
      });
    case Tool.file:
      return (data[Tool.file]?.items ?? []).map((file) => ({
        id: file.id,
        communityId: file.community_id ?? fallbackCommunityId,
        name: file.name,
        href: href(file.id, file.initiative_id),
        glyph: null,
        initiativeId: file.initiative_id,
        tags: file.tags,
        updatedAt: file.updated_at,
        detail: <Badge variant="secondary">{t(`detail.fileKind.${file.kind}`)}</Badge>,
      }));
    case Tool.queue:
      return (data[Tool.queue]?.items ?? []).map((queue) => ({
        id: queue.id,
        communityId: queue.community_id ?? fallbackCommunityId,
        name: queue.name,
        href: href(queue.id, queue.initiative_id),
        glyph: null,
        initiativeId: queue.initiative_id,
        tags: queue.tags,
        updatedAt: queue.updated_at,
      }));
    case Tool.counter_group:
      return (data[Tool.counter_group]?.items ?? []).map((group) => ({
        id: group.id,
        communityId: group.community_id ?? fallbackCommunityId,
        name: group.name,
        href: href(group.id, group.initiative_id),
        glyph: null,
        initiativeId: group.initiative_id,
        tags: group.tags,
        updatedAt: group.updated_at,
      }));
    case Tool.calendar:
      return (data[Tool.calendar]?.items ?? []).map((calendar) => ({
        id: calendar.id,
        communityId: calendar.community_id ?? fallbackCommunityId,
        name: calendar.name,
        href: href(calendar.id, calendar.initiative_id),
        glyph: <ColourDot colour={calendar.color} />,
        initiativeId: calendar.initiative_id,
        tags: calendar.tags,
        updatedAt: calendar.updated_at,
        detail: calendar.description,
      }));
    case Tool.dashboard:
      return (data[Tool.dashboard]?.items ?? []).map((dashboard) => ({
        id: dashboard.id,
        communityId: dashboard.community_id ?? fallbackCommunityId,
        name: dashboard.name,
        href: href(dashboard.id, dashboard.initiative_id),
        glyph: null,
        initiativeId: dashboard.initiative_id,
        tags: dashboard.tags,
        updatedAt: dashboard.updated_at,
        detail: dashboard.listing_uid ? (
          <Badge variant="secondary">{t("detail.fromMarketplace")}</Badge>
        ) : (
          t("detail.builtHere")
        ),
      }));
    case Tool.post:
      return (data[Tool.post]?.items ?? []).map((post) => ({
        id: post.id,
        communityId: post.community_id ?? fallbackCommunityId,
        name: post.name,
        href: href(post.id, post.initiative_id),
        glyph: null,
        initiativeId: post.initiative_id,
        tags: post.tags,
        updatedAt: post.updated_at,
        // The first line of the notice. A table of posts is a table of
        // things people said, and the headline alone rarely distinguishes two
        // of them — the server derives this from the body for exactly here,
        // with the people it mentions left in for the table to name.
        detail: post.excerpt,
      }));
    case Tool.wiki:
      return (data[Tool.wiki]?.items ?? []).map((wiki) => ({
        id: wiki.id,
        communityId: wiki.community_id ?? fallbackCommunityId,
        name: wiki.name,
        href: href(wiki.id, wiki.initiative_id),
        glyph: null,
        initiativeId: wiki.initiative_id,
        tags: wiki.tags,
        updatedAt: wiki.updated_at,
      }));
  }
}

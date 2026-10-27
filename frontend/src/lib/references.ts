/**
 * What each trigger reaches.
 *
 * `#` names anything that already exists. `[[ ]]` names a **tool**, and can
 * make one that does not exist yet — which is the whole difference between
 * them: a tool needs a name and the initiative the writer is already in, and
 * nothing else. A task needs a project, an event needs a calendar and a time,
 * so neither can be conjured from a name in a sentence.
 *
 * Derived from the tool enum, so a seventh is linkable the day it exists.
 */

import type { InitiativeRead, SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { isToolEnabled, TOOLS } from "@/lib/tools";

/**
 * A tool — or a task, a project's child rather than a tool of its own — as the
 * entity type a reference names it by.
 *
 * The two vocabularies spell every one of them the same word, so this is the
 * one place that says so rather than a cast at each call site. `references.test`
 * holds them to it: a tool whose spellings drifted apart would still compile,
 * and would quietly stop being excluded from its own comment thread's picker.
 */
export const referenceTypeFor = (
  tool: Tool | "task" | "wiki_page" | "collection"
): SearchEntityType => tool as unknown as SearchEntityType;

/**
 * The tools `[[ ]]` may offer in one initiative.
 *
 * An initiative can switch a tool off, and a tool that is off is not there to
 * link to — nor to create, which would be a way to put back something the
 * initiative chose not to have. Core tools have no switch and are always in.
 *
 * With no initiative loaded yet, every tool is offered: the search behind the
 * picker only returns what exists anyway, and the create option is gated
 * separately.
 */
export const linkableToolTypes = (
  initiative: InitiativeRead | null | undefined
): SearchEntityType[] =>
  TOOLS.filter((tool) => !initiative || isToolEnabled(tool, initiative)).map(referenceTypeFor);

/** Whether `[[ ]]` can make one of these from a name alone. */
export const isCreatableFromName = (
  entityType: SearchEntityType,
  initiative: InitiativeRead | null | undefined
): boolean =>
  Boolean(initiative) && (linkableToolTypes(initiative) as string[]).includes(entityType);

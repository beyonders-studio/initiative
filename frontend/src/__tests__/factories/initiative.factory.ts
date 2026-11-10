import type {
  InitiativeCan,
  InitiativeDirectoryEntry,
  InitiativeJoinRequestRead,
  InitiativeMemberRead,
  InitiativeRead,
  InitiativeRoleRead,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
import {
  DEFAULT_ENABLED_TOOLS,
  TOOLS,
  toolCreatePermission,
  toolViewPermission,
} from "@/lib/tools";

import { buildUserSummary } from "./user.factory";

let counter = 0;

type InitiativeToolSwitches = Pick<
  InitiativeRead,
  Extract<keyof InitiativeRead, `${string}_enabled`>
>;

export function resetCounter(): void {
  counter = 0;
}

export function buildInitiativeMember(
  overrides: Partial<InitiativeMemberRead> = {}
): InitiativeMemberRead {
  counter++;
  return {
    user: buildUserSummary(),
    role_id: null,
    role_name: null,
    role_display_name: null,
    is_manager: false,
    override_share_restrictions: false,
    oidc_managed: false,
    joined_at: "2026-01-15T00:00:00.000Z",
    presence: "offline",
    guest_until: null,
    ...overrides,
  };
}

/** What the reader may do in an initiative. Fail-closed like a member's
 *  defaults: the tools an initiative starts with may be viewed, nothing made,
 *  nothing run, and the roster read as any member reads it. */
export const initiativeCan = (overrides: Partial<InitiativeCan> = {}): InitiativeCan => ({
  manage: false,
  moderate: false,
  roster: true,
  view: TOOLS.filter((tool) => DEFAULT_ENABLED_TOOLS.has(tool)),
  create: [],
  ...overrides,
});

export function buildInitiative(overrides: Partial<InitiativeRead> = {}): InitiativeRead {
  counter++;
  return {
    id: counter,
    community_id: 1,
    name: `Initiative ${counter}`,
    description: `Description for initiative ${counter}`,
    color: "#3b82f6",
    archived_at: null,
    // Fail-closed, like the column default: an initiative is invite-only until
    // someone opens it.
    join_policy: "private",
    auto_join: false,
    keep_content_in: false,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    member_count: 0,
    role_display_name: null,
    can: initiativeCan(),
    // One `{plural}_enabled` master switch per tool, at the column defaults:
    // projects and files on, the rest opt-in. Derived from the registry so
    // a new tool arrives here without an edit.
    ...(Object.fromEntries(
      TOOLS.map((tool) => [toolViewPermission(tool), DEFAULT_ENABLED_TOOLS.has(tool)])
    ) as InitiativeToolSwitches),
    ...overrides,
  };
}

/**
 * A role with a complete permission map, the way the API answers: every key
 * has a value, viewing a core tool on and everything else off. Pass
 * `permissions` to override individual keys.
 */
export function buildInitiativeRole(
  overrides: Partial<InitiativeRoleRead> = {}
): InitiativeRoleRead {
  counter++;
  // Derived from the registry, like the backend's DEFAULT_PERMISSION_VALUES:
  // viewing a core (always-on) tool is on, everything else is off.
  const defaults = Object.fromEntries(
    TOOLS.flatMap((tool) => [
      [toolViewPermission(tool), DEFAULT_ENABLED_TOOLS.has(tool)],
      [toolCreatePermission(tool), false],
    ])
  ) as Record<PermissionKey, boolean>;
  const { permissions, ...rest } = overrides;
  return {
    id: counter,
    name: `role_${counter}`,
    display_name: `Role ${counter}`,
    is_builtin: false,
    is_manager: false,
    override_share_restrictions: false,
    position: counter,
    permissions: { ...defaults, ...permissions },
    plugin_permissions: [],
    member_count: 0,
    ...rest,
  };
}

/** One card in the community's initiative directory (`GET /initiatives/directory`). */
export function buildInitiativeDirectoryEntry(
  overrides: Partial<InitiativeDirectoryEntry> = {}
): InitiativeDirectoryEntry {
  counter++;
  return {
    id: counter,
    name: `Initiative ${counter}`,
    description: `Description for initiative ${counter}`,
    color: "#3b82f6",
    join_policy: "open",
    auto_join: false,
    member_count: 3,
    is_member: false,
    role_display_name: null,
    has_pending_request: false,
    // Reads zero for anyone who couldn't answer the queue anyway.
    pending_join_request_count: 0,
    ...overrides,
  };
}

/** One row of an initiative's join-request queue. Pending and never denied
 *  before — the plain knock a manager sees most of the time. */
export function buildInitiativeJoinRequest(
  overrides: Partial<InitiativeJoinRequestRead> = {}
): InitiativeJoinRequestRead {
  counter++;
  return {
    id: counter,
    initiative_id: 1,
    user: buildUserSummary(),
    status: "pending",
    message: null,
    created_at: "2026-01-15T00:00:00.000Z",
    resolved_at: null,
    resolved_by: null,
    prior_denials: 0,
    ...overrides,
  };
}

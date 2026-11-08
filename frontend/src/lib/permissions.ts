/**
 * Platform capability helpers (frontend mirror of `app.core.capabilities`).
 *
 * The backend computes the authoritative capability set for the current user
 * and ships it on `UserRead.capabilities`. The frontend never derives
 * capabilities from the role itself — it only reads the list — so the two
 * stay in lockstep. These string constants must match the backend
 * `Capability` enum values exactly (held by `permissions.test.ts` against the
 * generated enum).
 */

import { CommunityRole, type ToolCan, type UserRead } from "@/api/generated/initiativeAPI.schemas";

export const Capability = {
  usersRead: "users.read",
  usersAgeUnblock: "users.age_unblock",
  usersManage: "users.manage",
  usersDelete: "users.delete",
  rolesAssign: "roles.assign",
  communitiesRead: "communities.read",
  communitiesManage: "communities.manage",
  communitiesSuspend: "communities.suspend",
  billingSupport: "billing.support",
  billingInsights: "billing.insights",
  billingContracts: "billing.contracts",
  billingDirectory: "billing.directory",
  billingControl: "billing.control",
  announcementsManage: "announcements.manage",
  contentModerate: "content.moderate",
  dataBypass: "data.bypass",
  accessRequest: "access.request",
  accessRequestAny: "access.request_any",
  accessApprove: "access.approve",
  configManage: "config.manage",
  pluginsManage: "plugins.manage",
} as const;

export type Capability = (typeof Capability)[keyof typeof Capability];

/** A minimal shape so callers can pass the auth user (or any object with a
 * capabilities list) without importing the full `UserRead`. */
type WithCapabilities = Pick<UserRead, "capabilities"> | null | undefined;

/** True iff the user's standing role grants `capability`. */
export function hasCapability(user: WithCapabilities, capability: Capability): boolean {
  return user?.capabilities?.includes(capability) ?? false;
}

/** True iff the user holds at least one of the given capabilities. */
export function hasAnyCapability(user: WithCapabilities, capabilities: Capability[]): boolean {
  return capabilities.some((c) => hasCapability(user, c));
}

/** Capabilities behind the **Platform settings** area (app-wide config:
 * auth, branding, email, AI, plug-in services). Owner-only in practice. */
const PLATFORM_SETTINGS_CAPABILITIES: Capability[] = [
  Capability.configManage,
  Capability.pluginsManage,
];

/** Capabilities behind the **Operator dashboard** area (operational: platform
 * users + time-bound access grants). */
const OPERATOR_DASHBOARD_CAPABILITIES: Capability[] = [
  Capability.usersRead,
  Capability.usersAgeUnblock,
  Capability.usersManage,
  Capability.communitiesRead,
  Capability.communitiesManage,
  Capability.announcementsManage,
  Capability.billingInsights,
  Capability.billingContracts,
  Capability.billingDirectory,
  Capability.billingControl,
  Capability.contentModerate,
  Capability.accessRequest,
  Capability.accessApprove,
];

/** True iff the user can configure the platform (Platform settings area). */
export function canManagePlatformConfig(user: WithCapabilities): boolean {
  return hasAnyCapability(user, PLATFORM_SETTINGS_CAPABILITIES);
}

/** True iff the user can reach the operational Operator dashboard area. */
export function canAccessOperatorDashboard(user: WithCapabilities): boolean {
  return hasAnyCapability(user, OPERATOR_DASHBOARD_CAPABILITIES);
}

/** True iff the user can access *either* platform area — used for coarse
 * gating (no-community layout choice, route guards). */
export function canAccessPlatformAreas(user: WithCapabilities): boolean {
  return canManagePlatformConfig(user) || canAccessOperatorDashboard(user);
}

/**
 * Whether a roster row's rung administers the community — somebody else's
 * place in it, as the roster reports it. What the viewer may do there is the
 * community's own `can`.
 */
export const isAdminRole = (communityRole: string | null | undefined): boolean =>
  communityRole === CommunityRole.admin || communityRole === CommunityRole.superadmin;

/** The rungs a roster offers, in order. The seat is offered only to somebody
 *  who holds it: an admin can neither appoint nor demote one. */
export const assignableCommunityRoles = (holdsSeat: boolean): CommunityRole[] =>
  holdsSeat
    ? [CommunityRole.superadmin, CommunityRole.admin, CommunityRole.member]
    : [CommunityRole.admin, CommunityRole.member];

/** Whether the viewer may take `action` on every one of `items` — a selection
 *  read against each row's server-computed `can`. */
export const everyCan = (items: readonly { can: ToolCan }[], action: keyof ToolCan): boolean =>
  items.length > 0 && items.every((item) => item.can[action]);

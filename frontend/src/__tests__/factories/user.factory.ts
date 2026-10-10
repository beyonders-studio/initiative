import type {
  Capability,
  OwnedDecoration,
  UserCommunityMember,
  UserEmailRead,
  UserProfile,
  UserPublic,
  UserRead,
  UserRole,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

// Test-only mirror of the backend `app.core.capabilities` ladder, so a factory
// user built with `role: "owner"` lands the capabilities production would send.
// The backend (`UserRead.capabilities`) remains the single source of truth at
// runtime; this only fills the gap in synthetic fixtures.
const ROLE_CAPABILITIES: Record<UserRole, Capability[]> = {
  member: [],
  support: ["access.request", "users.age_unblock", "users.read"],
  moderator: [
    "access.request",
    "content.moderate",
    "users.age_unblock",
    "users.manage",
    "users.read",
  ],
  operator: [
    "access.approve",
    "access.request",
    "announcements.manage",
    "billing.insights",
    "content.moderate",
    "data.bypass",
    "communities.manage",
    "roles.assign",
    "users.age_unblock",
    "users.delete",
    "users.manage",
    "users.read",
  ],
  owner: [
    "access.approve",
    "announcements.manage",
    "plugins.manage",
    "billing.insights",
    "config.manage",
    "content.moderate",
    "data.bypass",
    "communities.manage",
    "roles.assign",
    "users.age_unblock",
    "users.delete",
    "users.manage",
    "users.read",
  ],
};

export function capabilitiesForRole(role: UserRole): Capability[] {
  return ROLE_CAPABILITIES[role] ?? [];
}

export function buildUserPublic(overrides: Partial<UserPublic> = {}): UserPublic {
  counter++;
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    display_name: `User ${counter}`,
    avatar_url: null,
    status: "active",
    ...overrides,
  };
}

/** The slim projection the member search/typeahead endpoints return — no
 *  email, role, or timestamps. Use this for picker fixtures so a test can't
 *  pass on a field the real payload never carries. */
export function buildUserSummary(overrides: Partial<UserSummary> = {}): UserSummary {
  counter++;
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    display_name: `User ${counter}`,
    avatar_url: null,
    status: "active",
    profile_decorations: null,
    community_role: null,
    ...overrides,
  };
}

/**
 * One address on an account, as its owner reads it.
 *
 * Defaults describe the address somebody signed up with: confirmed, primary,
 * and the one the account was made from. Pass `verified: false` for a claim
 * still waiting on its link, or `source: "synthetic"` for the stand-in an IdP
 * that asserted no address leaves behind.
 */
export function buildUserEmail(overrides: Partial<UserEmailRead> = {}): UserEmailRead {
  counter++;
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    verified: true,
    is_primary: true,
    source: "signup",
    created_at: "2026-01-01T00:00:00Z",
    last_login_at: null,
    ...overrides,
  };
}

export function buildUser(overrides: Partial<UserRead> = {}): UserRead {
  counter++;
  const role = overrides.role ?? "member";
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    username_chosen: true,
    // Answered, like the handle: a test that is not about the age gate should
    // never meet it. The gate's own tests override these two.
    age_confirmed_at: "2026-01-01T00:00:00Z",
    // Agreed, for the same reason: only the terms gate's own tests want an
    // account that has not.
    legal_acceptance_required: false,
    // Answered, so the one-time birthdate screen does not stand in front of
    // whatever a test renders.
    birthdate_on_file: true,
    birthdate_required: false,
    age_below_minimum_at: null,
    avatar_url: null,
    role: "member",
    capabilities: capabilitiesForRole(role),
    can_create_communities: true,
    status: "active",
    presence: "offline",
    cookie_consent: null,
    email_verified: true,
    // Signs in with a password, like most accounts. A test about the
    // passwordless account overrides it.
    has_password: true,
    // And is asked for it when confirming a change, which the deployment's
    // own posture can turn off.
    password_required: true,
    has_federated_identity: false,
    demo_expires_at: null,
    demo_community_id: null,
    initiative_roles: [],
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    custom_status: { emoji: null, text: null },
    profile_decorations: {
      banner: null,
      frame: null,
      frame_tint: [],
      trophies: [],
      grad_year: null,
    },
    week_starts_on: 0,
    time_format: "system",
    timezone: "America/New_York",
    recent_tabs_limit: 20,
    event_reminder_minutes_before: null,
    last_overdue_notification_at: null,
    last_task_assignment_digest_at: null,
    color_theme: "kobold",
    task_completion_visual_feedback: "none",
    task_completion_audio_feedback: false,
    task_completion_haptic_feedback: false,
    locale: "en",
    ...overrides,
  };
}

export function buildUserCommunityMember(
  overrides: Partial<UserCommunityMember> = {}
): UserCommunityMember {
  counter++;
  const communityRole = overrides.community_role ?? "member";
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    display_name: `User ${counter}`,
    avatar_url: null,
    community_role: communityRole,
    oidc_managed: false,
    api_keys_allowed: null,
    status: "active",
    created_at: "2026-01-15T00:00:00.000Z",
    initiative_roles: [],
    ...overrides,
  };
}

/** A member's profile, as the rest of their community sees them. Bare by default —
 *  no status and nothing worn — so a test that asserts on a decoration has to
 *  have put it there. */
export function buildUserProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  counter++;
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    avatar_url: null,
    status: "active",
    custom_status: { emoji: null, text: null },
    profile_decorations: {
      banner: null,
      frame: null,
      frame_tint: [],
      trophies: [],
      grad_year: null,
    },
    presence: "offline",
    joined_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

/** One decoration in somebody's library. Shipped (no pack) by default. */
export function buildOwnedDecoration(overrides: Partial<OwnedDecoration> = {}): OwnedDecoration {
  return {
    id: "core.aurora",
    kind: "banner",
    name: null,
    source: null,
    image_url: null,
    ...overrides,
  };
}

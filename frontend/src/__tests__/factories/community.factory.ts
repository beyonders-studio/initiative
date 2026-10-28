import type {
  CommunityBannerRead,
  CommunityCan,
  CommunityInviteStatus,
  CommunityRead,
} from "@/api/generated/initiativeAPI.schemas";
import { isAdminRole } from "@/lib/permissions";

let counter = 0;

export function buildBanner(overrides: Partial<CommunityBannerRead> = {}): CommunityBannerRead {
  return {
    image_url: null,
    color: "#2563eb",
    text_color: "#ffffff",
    text_align: "center",
    fade: "strong",
    ...overrides,
  };
}

/** What the server answers for a membership at `role`: an administrator runs
 *  the community and its work, and the seat is the top rung. */
export function communityCan(
  role: string = "member",
  overrides: Partial<CommunityCan> = {}
): CommunityCan {
  const administers = isAdminRole(role);
  return {
    enter: true,
    content: true,
    administer: administers,
    configure: administers,
    administer_content: administers,
    seat: role === "superadmin",
    community_wide: role !== "guest",
    use_api: true,
    ...overrides,
  };
}

export function resetCounter(): void {
  counter = 0;
}

export function buildCommunity(overrides: Partial<CommunityRead> = {}): CommunityRead {
  counter++;
  const role = overrides.role ?? "member";
  return {
    id: counter,
    name: `Community ${counter}`,
    description: `Description for community ${counter}`,
    icon_url: null,
    location: null,
    banner_card_url: null,
    banner: buildBanner(),
    online_count: 0,
    role,
    can: communityCan(role),
    position: counter - 1,
    display_name: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    retention_days: null,
    max_storage_bytes: null,
    max_users: null,
    max_guests: null,
    member_count: 1,
    tier_name: null,
    status: null,
    content_read_only: false,
    contact_email: null,
    auth_options: null,
    is_community: false,
    categories: [],
    has_adult_content: null,
    ...overrides,
  };
}

export function buildCommunityInviteStatus(
  overrides: Partial<CommunityInviteStatus> = {}
): CommunityInviteStatus {
  counter++;
  return {
    code: `invite-code-${counter}`,
    community_id: counter,
    community_name: `Community ${counter}`,
    is_valid: true,
    reason: null,
    expires_at: null,
    max_uses: null,
    uses: 0,
    guest_days: null,
    ...overrides,
  };
}

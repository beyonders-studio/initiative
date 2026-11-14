import type {
  MarketplaceListingDetail,
  MarketplaceListingSummary,
  MarketplaceVersionRead,
  PluginWidgetCatalogEntry,
} from "@/api/generated/initiativeAPI.schemas";
import type { ProjectListingEnvelope } from "@/lib/projectListing";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildMarketplaceVersion(
  overrides: Partial<MarketplaceVersionRead> = {}
): MarketplaceVersionRead {
  return {
    version: "1.0.0",
    release_notes: null,
    min_app_version: null,
    published_at: "2026-01-15T00:00:00.000Z",
    compatible: true,
    ...overrides,
  };
}

/**
 * A browse card's listing.
 *
 * Defaults to the shape a shipped listing has — `builtin`, published by
 * Initiative — because that is the one every deployment always has. Pass
 * `source`, `publisher` and `first_party: false` together to build the
 * non-first-party case: a listing a registry signed, or one an operator added.
 */
export function buildMarketplaceListing(
  overrides: Partial<MarketplaceListingSummary> = {}
): MarketplaceListingSummary {
  counter++;
  return {
    id: counter,
    uid: `TESTLISTING${String(counter).padStart(3, "0")}`,
    public_id: `core.listing-${counter}`,
    kind: "dashboard",
    source: "builtin",
    name: `Listing ${counter}`,
    publisher: "Initiative",
    first_party: true,
    description: "What this listing is for.",
    avatar_url: "/marketplace/test.svg",
    images: [],
    installs_count: 0,
    available: true,
    latest_version: buildMarketplaceVersion(),
    installable: true,
    unavailable: null,
    updated_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildMarketplaceListingDetail(
  overrides: Partial<MarketplaceListingDetail> = {}
): MarketplaceListingDetail {
  const summary = buildMarketplaceListing();
  return {
    ...summary,
    long_description: null,
    definition: null,
    example: null,
    requested_scopes: [],
    grantable_scopes: [],
    plugin_names: {},
    has_initiative_surfaces: false,
    callers: [],
    ...overrides,
  };
}

/**
 * One install in the plug-in widget catalog: `acme.shop`, with one read
 * endpoint, `orders`, that takes a `range` and returns a list of `status` and
 * `total`, and no widgets of its own.
 */
export function buildPluginCatalogEntry(
  overrides: Partial<PluginWidgetCatalogEntry> = {}
): PluginWidgetCatalogEntry {
  counter++;
  return {
    plugin_id: counter,
    plugin_uid: `PLUGIN${String(counter).padStart(8, "0")}`,
    public_id: "acme.shop",
    name: "Shop",
    enabled: true,
    widgets: [],
    endpoints: [
      {
        id: "plugin.acme.shop.orders",
        cache_ttl_seconds: 60,
        params: [{ key: "range", type: "string", label: { en: "Range" } }],
        returns: [
          { key: "status", type: "string", list: true },
          { key: "total", type: "number", list: true },
        ],
      },
    ],
    ...overrides,
  };
}

/**
 * What a project listing publishes: its export envelope, dated as a listing
 * stores dates, with the project starting on the anchor day (2000-01-03).
 *
 * Three columns, a select property, and two tasks in the first column: one due
 * on the third day with half its checklist done, one due in the fourth week.
 */
export function buildProjectListingEnvelope(
  overrides: Partial<ProjectListingEnvelope> = {}
): ProjectListingEnvelope {
  return {
    project: { name: "Launch plan", start_date: "2000-01-03", end_date: "2000-01-31" },
    task_statuses: [
      { name: "To do", category: "todo", position: 0, color: "#94A3B8", icon: "circle" },
      { name: "Doing", category: "in_progress", position: 1, color: null, icon: null },
      { name: "Done", category: "done", position: 2, color: "#34D399", icon: "circle-check" },
    ],
    property_definitions: [
      {
        name: "Size",
        type: "select",
        position: 0,
        options: [
          { value: "s", label: "Small", color: "#60A5FA" },
          { value: "l", label: "Large", color: "#F97316" },
        ],
      },
    ],
    tasks: [
      {
        title: "Draft the announcement",
        priority: "high",
        start_date: null,
        due_date: "2000-01-05T09:00:00",
        status_name: "To do",
        checklist: [
          { text: "Outline", done: true },
          { text: "Review", done: false },
        ],
        properties: [{ property_name: "Size", property_type: "select", value_text: "s" }],
      },
      {
        title: "Ship it",
        priority: "low",
        start_date: null,
        due_date: "2000-01-24T09:00:00",
        status_name: "To do",
        checklist: [],
        properties: [],
      },
    ],
    ...overrides,
  };
}

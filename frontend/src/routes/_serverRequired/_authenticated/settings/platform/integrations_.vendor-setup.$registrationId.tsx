import { createFileRoute } from "@tanstack/react-router";

import { SettingsVendorSetupPage } from "@/pages/SettingsVendorSetupPage";

export interface VendorSetupSearch {
  code?: string;
  state?: string;
}

/** What the server takes for each, so a longer one is not cut short. */
const MAX_LENGTH = 4000;

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value ? value.slice(0, MAX_LENGTH) : undefined;

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations_/vendor-setup/$registrationId"
)({
  // Where a vendor's setup sends the operator back, with its code and the
  // state the setup started with.
  validateSearch: (search: Record<string, unknown>): VendorSetupSearch => ({
    code: text(search.code),
    state: text(search.state),
  }),
  component: SettingsVendorSetupPage,
});

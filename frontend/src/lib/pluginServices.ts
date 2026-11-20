/** Helpers for the deployment-level plug-in service registration form. */

import { isAxiosError } from "axios";

import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import { getErrorCode } from "@/lib/errorMessage";

/**
 * Whether Initiative calls the registration's plug-in: a container, the one
 * kind with an address, origins and a key set. A declarative plug-in's calls
 * are Initiative's own and a tool plug-in runs no code, so either is live
 * with none of them set.
 */
export const runsAService = (registration: Pick<PluginServiceRegistrationRead, "kind">): boolean =>
  registration.kind === "container";

/**
 * What a plug-in's vendor check refused a save for: the vendor fields it
 * blames, the plug-in's own message by language, and what the vendor holds
 * instead when the check says.
 */
export interface VendorCheckRefusal {
  fields: string[];
  message: Record<string, string>;
  shows: string | null;
}

/** The codes a vendor check refuses a save with. */
const VENDOR_CHECK_CODES = new Set([
  "PLUGIN_SERVICE_VENDOR_CHECK_REFUSED",
  "PLUGIN_SERVICE_VENDOR_KEY_UNUSABLE",
]);

/** A save's vendor check refusal, or null for any other failure. */
export const vendorCheckRefusalIn = (error: unknown): VendorCheckRefusal | null => {
  if (!VENDOR_CHECK_CODES.has(getErrorCode(error) ?? "") || !isAxiosError(error)) return null;
  const params =
    (error.response?.data as { params?: Record<string, string> } | undefined)?.params ?? {};
  let message: Record<string, string> = {};
  if (params.message) {
    try {
      const parsed: unknown = JSON.parse(params.message);
      if (parsed && typeof parsed === "object") message = parsed as Record<string, string>;
    } catch {
      // A message that is not JSON is shown as the code's own wording.
    }
  }
  return {
    fields: params.fields ? params.fields.split("\n") : [],
    message,
    shows: params.shows ?? null,
  };
};

/** Split a textarea of origins into the list the API expects. */
export const parseAllowedOrigins = (value: string): string[] =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

/**
 * Send the browser to the vendor's setup page with the manifest, as the form
 * post the vendor's manifest flow takes. The page leaves for the vendor.
 */
export const postToVendor = (setup: { action: string; manifest: string; state: string }) => {
  const form = document.createElement("form");
  form.method = "post";
  form.action = `${setup.action}?state=${encodeURIComponent(setup.state)}`;
  form.hidden = true;
  const manifest = document.createElement("input");
  manifest.type = "hidden";
  manifest.name = "manifest";
  manifest.value = setup.manifest;
  form.appendChild(manifest);
  document.body.appendChild(form);
  form.submit();
};

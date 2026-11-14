import { createFileRoute } from "@tanstack/react-router";

import { BrandingPage } from "@/pages/platform/BrandingPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/branding")({
  component: BrandingPage,
});

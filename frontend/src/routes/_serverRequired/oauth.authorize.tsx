import { createFileRoute } from "@tanstack/react-router";

import { PluginSignInPage, SIGN_IN_PARAMS, type SignInSearch } from "@/pages/PluginSignInPage";

export const Route = createFileRoute("/_serverRequired/oauth/authorize")({
  // The request as the plug-in sent it, its text parameters only.
  validateSearch: (search: Record<string, unknown>): SignInSearch =>
    Object.fromEntries(
      SIGN_IN_PARAMS.flatMap((name) =>
        typeof search[name] === "string" ? [[name, search[name] as string]] : []
      )
    ),
  component: PluginSignInPage,
});

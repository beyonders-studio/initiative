import { lazy, Suspense, useLayoutEffect } from "react";

import { claimHelp, useHelpState } from "@/components/help/helpStore";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";

const HelpPanel = lazy(() =>
  import("@/components/help/HelpPanel").then((module) => ({ default: module.HelpPanel }))
);

/**
 * Help, drawn once at the root: the panel while it is open, loaded the first
 * time it is. A draft belongs to the server and account it was written under,
 * and is dropped when either changes.
 */
export const HelpHost = () => {
  const help = useHelpState();
  const { user } = useAuth();
  const { serverUrl } = useServer();
  const owner = `${serverUrl ?? ""} ${user?.id ?? ""}`;
  // Before paint, so another account never sees what was written.
  useLayoutEffect(() => claimHelp(owner), [owner]);
  if (!help.open) return null;
  return (
    <Suspense fallback={null}>
      <HelpPanel help={help} />
    </Suspense>
  );
};

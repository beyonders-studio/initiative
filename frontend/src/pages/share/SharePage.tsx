import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { markPendingShareOpened, setPendingShare, usePendingShare } from "@/lib/share/pendingShare";
import { ShareWizard } from "@/pages/share/ShareWizard";

/**
 * Where something shared from another app's share sheet is made into a task, a
 * document, an uploaded file or a post. With nothing waiting to be shared there
 * is nothing to do here, and it goes home.
 */
export function SharePage() {
  const router = useRouter();
  const share = usePendingShare();

  useEffect(() => {
    if (share) {
      markPendingShareOpened();
    } else {
      void router.navigate({ to: "/", replace: true });
    }
  }, [share, router]);

  // Leave first, then let the share go: cleared while still here, the empty
  // page would send somebody home instead of to what they just made.
  const finish = async (path?: string) => {
    await router.navigate(path ? { to: path } : { to: "/", replace: true });
    setPendingShare(null);
  };

  if (!share) return null;
  return <ShareWizard key={share.id} share={share} onDone={(path) => void finish(path)} />;
}

import { useEffect } from "react";

import { getAuthToken } from "@/api/client";
import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useCommunities } from "@/hooks/useCommunities";
import { openLiveSocket } from "@/lib/liveSocket";
import { toolRouteSegment } from "@/lib/tools";
import { buildCommunityWsUrl } from "@/lib/wsUrl";

/**
 * Subscribe to one tool entity's change signal (a counter group's) and
 * refetch it and its lists on every change, so React Query reads
 * the latest state through the normal endpoints. A frame names a change and
 * never carries the resource.
 *
 * Built on the shared live socket, so it authenticates in its first frame,
 * reconnects with jittered backoff, and notices a connection that has gone
 * quiet. The credential is read as each first frame is written, so a renewed
 * token does not tear the socket down; a reconnect refetches, since whatever
 * changed while it was away was said to nobody.
 */
export function useToolRealtime(tool: Tool, id: number | null): void {
  const { activeCommunityId } = useCommunities();

  useEffect(() => {
    if (!id || !activeCommunityId) return;

    const refetch = () => void invalidate(q.tool(tool, id));
    let opened = 0;
    const connection = openLiveSocket({
      url: buildCommunityWsUrl(activeCommunityId, `${toolRouteSegment(tool)}/${id}/ws`),
      // Null is fine — the server reads the session cookie, which is the web
      // path.
      auth: () => ({ token: getAuthToken() }),
      onFrame: (frame) => {
        if ((frame as { heartbeat?: boolean } | null)?.heartbeat) return;
        refetch();
      },
      onStatus: (connected) => {
        if (!connected) return;
        opened += 1;
        if (opened > 1) refetch();
      },
    });

    return () => connection.close();
  }, [tool, id, activeCommunityId]);
}

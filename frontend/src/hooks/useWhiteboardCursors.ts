import type { Collaborator, SocketId } from "@excalidraw/excalidraw/types";
import type { ProviderAwareness } from "@lexical/yjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getUserColorHsl, userColorHashId } from "@/ui/lib/userColor";

interface WhiteboardUser {
  id: number;
  name: string;
}

interface Pointer {
  x: number;
  y: number;
  tool: "pointer" | "laser";
}

interface WhiteboardAwarenessState {
  whiteboard_user?: { id: number; name: string };
  whiteboard_pointer?: Pointer & { button?: "up" | "down"; updatedAt: number };
}

interface UseWhiteboardCursorsArgs {
  awareness: ProviderAwareness | null;
  clientId: number | null;
  user: WhiteboardUser | null;
  enabled: boolean;
}

export function useWhiteboardCursors({
  awareness,
  clientId,
  user,
  enabled,
}: UseWhiteboardCursorsArgs) {
  const [collaborators, setCollaborators] = useState<Map<SocketId, Collaborator>>(() => new Map());
  // Coalesce pointer events into at most one awareness update per paint.
  // Excalidraw's onPointerUpdate can fire faster than 60Hz on high-refresh
  // devices; a fixed ms throttle either drops the trailing sample (leaving
  // peers on a stale final position) or runs below display rate. rAF aligns
  // with the browser's paint cycle, so sends match what the user can see.
  const pendingPointerRef = useRef<{ pointer: Pointer; button: "up" | "down" } | null>(null);
  const rafIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || !awareness || !user) return;
    awareness.setLocalStateField("whiteboard_user", {
      id: user.id,
      name: user.name,
    });
    return () => {
      // Clear immediately so peers drop our cursor instead of waiting for the
      // 30s awareness timeout.
      awareness.setLocalStateField("whiteboard_user", null);
      awareness.setLocalStateField("whiteboard_pointer", null);
    };
  }, [awareness, enabled, user]);

  useEffect(() => {
    if (!enabled || !awareness || clientId == null) {
      setCollaborators(new Map());
      return;
    }
    const rebuild = () => {
      const states = awareness.getStates() as unknown as Map<number, WhiteboardAwarenessState>;
      const next = new Map<SocketId, Collaborator>();
      states.forEach((state, peerClientId) => {
        if (peerClientId === clientId) return;
        const peerUser = state?.whiteboard_user;
        if (!peerUser) return;
        const pointer = state.whiteboard_pointer;
        const peerColor = getUserColorHsl(peerUser.id);
        next.set(String(peerClientId) as SocketId, {
          // Excalidraw's cursor rendering runs getClientColor(socketId, collaborator)
          // which hashes `collaborator.id` if present. Set it to the user id
          // string so the cursor hue matches getUserColorHsl(user.id).
          id: userColorHashId(peerUser.id),
          username: peerUser.name,
          color: { background: peerColor, stroke: peerColor },
          pointer: pointer ? { x: pointer.x, y: pointer.y, tool: pointer.tool } : undefined,
          button: pointer?.button ?? "up",
        });
      });
      setCollaborators(next);
    };
    rebuild();
    awareness.on("update", rebuild);
    return () => {
      awareness.off("update", rebuild);
    };
  }, [awareness, clientId, enabled]);

  const publishPointer = useCallback(
    (pointer: Pointer, button: "up" | "down") => {
      if (!enabled || !awareness) return;
      pendingPointerRef.current = { pointer, button };
      if (rafIdRef.current !== null) return;
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null;
        const next = pendingPointerRef.current;
        pendingPointerRef.current = null;
        if (!next) return;
        awareness.setLocalStateField("whiteboard_pointer", {
          x: next.pointer.x,
          y: next.pointer.y,
          tool: next.pointer.tool,
          button: next.button,
          updatedAt: Date.now(),
        });
      });
    },
    [awareness, enabled]
  );

  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      pendingPointerRef.current = null;
    };
  }, []);

  return useMemo(() => ({ collaborators, publishPointer }), [collaborators, publishPointer]);
}

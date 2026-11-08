import { type RefObject, useEffect, useEffectEvent } from "react";

/**
 * Calls `receive` with each message the frame's own window posts from
 * `origin`. Messages from any other window or origin are ignored; a null
 * origin reads nothing.
 */
export function useFrameMessages(
  frame: RefObject<HTMLIFrameElement | null>,
  origin: string | null,
  receive: (data: unknown) => void
): void {
  const onMessage = useEffectEvent(receive);
  useEffect(() => {
    if (!origin) return;
    const listener = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== origin) return;
      onMessage(event.data);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [frame, origin]);
}

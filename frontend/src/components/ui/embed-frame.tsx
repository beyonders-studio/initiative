import type React from "react";
import { useEffect, useRef, useState } from "react";

/** The tallest a frame grows to fit what it reports. */
const MAX_HEIGHT = 2000;

export interface EmbedFrameProps {
  src: string;
  title: string;
  allow?: string;
  referrerPolicy?: React.HTMLAttributeReferrerPolicy;
  sandbox?: string;
  /** Reads a height from a message the frame posts, or null for any other message. */
  heightOf?: (data: unknown) => number | null;
  className?: string;
}

/**
 * Another site's page, framed. It takes the height its page reports, read
 * only from messages its own frame posts from the origin it was given.
 */
export function EmbedFrame({
  src,
  title,
  allow,
  referrerPolicy,
  sandbox,
  heightOf,
  className,
}: EmbedFrameProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number | null>(null);

  useEffect(() => {
    if (!heightOf) return;
    const origin = new URL(src).origin;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== origin) return;
      const reported = heightOf(event.data);
      if (reported !== null && reported > 0) setHeight(Math.min(reported, MAX_HEIGHT));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [src, heightOf]);

  return (
    <iframe
      ref={frame}
      src={src}
      title={title}
      allow={allow}
      referrerPolicy={referrerPolicy}
      sandbox={sandbox}
      allowFullScreen
      className={className}
      style={height === null ? undefined : { height }}
    />
  );
}

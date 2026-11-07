import type React from "react";
import { useRef, useState } from "react";

import { isOwnOrigin } from "@/api/client";
import { useFrameMessages } from "@/hooks/useFrameMessages";

/** The tallest a frame grows to fit what it reports. */
const MAX_HEIGHT = 2000;

/** What every embedded page may do: run, keep its own storage, open its links as ordinary tabs, take forms, present, download and ask to use its storage. */
const EMBED_SANDBOX =
  "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-forms allow-presentation allow-downloads allow-modals allow-storage-access-by-user-activation";

/** Where a frame that reports its height starts, before its page reports one. */
export const POST_FRAME_CLASS = "h-60 w-[550px] max-w-full border-0";

export interface EmbedFrameProps {
  src: string;
  title: string;
  allow?: string;
  referrerPolicy?: React.HTMLAttributeReferrerPolicy;
  /** Reads a height from a message the frame posts, or null for any other message. */
  heightOf?: (data: unknown) => number | null;
  className?: string;
}

/**
 * Another site's page, framed and sandboxed. It takes the height its page
 * reports, and shows nothing for an address on the app's or the server's origin.
 */
export function EmbedFrame({
  src,
  title,
  allow,
  referrerPolicy,
  heightOf,
  className,
}: EmbedFrameProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number | null>(null);

  useFrameMessages(frame, heightOf ? new URL(src).origin : null, (data) => {
    const reported = heightOf?.(data) ?? null;
    if (reported !== null && reported > 0) setHeight(Math.min(reported, MAX_HEIGHT));
  });

  if (isOwnOrigin(src)) return null;

  return (
    <iframe
      ref={frame}
      src={src}
      title={title}
      allow={allow}
      referrerPolicy={referrerPolicy}
      sandbox={EMBED_SANDBOX}
      allowFullScreen
      className={className}
      style={height === null ? undefined : { height }}
    />
  );
}

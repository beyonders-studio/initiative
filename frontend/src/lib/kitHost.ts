import { Link } from "@tanstack/react-router";
import type { ComponentType } from "react";

import { isOwnOrigin } from "@/api/client";
import { toast } from "@/lib/mascotToast";
import { canCapturePhoto, capturePhoto } from "@/lib/nativeCamera";
import { getItem, setItem } from "@/lib/storage";
import { type HostLinkProps, setHost } from "@/ui/host";

/**
 * Hand the UI kit what it takes from Initiative: the mascot's toasts, the
 * phone's camera, the router's links, the device's storage, the emoji data
 * this app serves and the origins that are its own.
 *
 * Called at boot once storage is ready, before anything renders; the reader's
 * clock follows the account through `useClockSync`.
 */
export const connectKit = (): void =>
  setHost({
    toast,
    camera: canCapturePhoto() ? { capture: capturePhoto } : null,
    Link: Link as unknown as ComponentType<HostLinkProps>,
    storage: { getItem, setItem },
    emojibaseUrl: __EMOJIBASE_URL__,
    isOwnOrigin,
  });

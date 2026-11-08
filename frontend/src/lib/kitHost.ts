import { Link } from "@tanstack/react-router";
import type { ComponentType } from "react";

import { isOwnOrigin } from "@/api/client";
import { toast } from "@/lib/mascotToast";
import { canCapturePhoto, capturePhoto } from "@/lib/nativeCamera";
import { openExternal } from "@/lib/openExternal";
import { getItem, setItem } from "@/lib/storage";
import { type HostLinkProps, setHost } from "@/ui/host";

/**
 * Hand the UI kit what it takes from Initiative: the mascot's toasts, the
 * phone's camera, the router's links, the phone's browser sheet, the device's
 * storage, the emoji data this app serves and the origins that are its own.
 *
 * Each is called through when the kit uses it rather than read here, so the
 * host holds nothing a module would have to hand over at boot.
 *
 * Called at boot once storage is ready, before anything renders; the reader's
 * clock follows the account through `useClockSync`.
 */
export const connectKit = (): void =>
  setHost({
    toast: {
      success: (message) => toast.success(message),
      error: (message) => toast.error(message),
    },
    camera: canCapturePhoto() ? { capture: (source) => capturePhoto(source) } : null,
    Link: Link as unknown as ComponentType<HostLinkProps>,
    openExternal: (url) => openExternal(url),
    storage: { getItem: (key) => getItem(key), setItem: (key, value) => setItem(key, value) },
    emojibaseUrl: __EMOJIBASE_URL__,
    isOwnOrigin: (url) => isOwnOrigin(url),
  });

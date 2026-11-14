import { Link, useBlocker } from "@tanstack/react-router";
import type { ComponentType } from "react";

import { isOwnOrigin } from "@/api/client";
import { previewRecurrence } from "@/api/generated/recurrence/recurrence";
import { toast } from "@/lib/mascotToast";
import { canCapturePhoto, capturePhoto } from "@/lib/nativeCamera";
import { openExternal } from "@/lib/openExternal";
import { getItem, setItem } from "@/lib/storage";
import { getUserDisplayName, toMember } from "@/lib/userDisplay";
import { type Blocker, type HostLinkProps, setHost } from "@/ui/host";
import type { UserValue } from "@/ui/properties/propertyHelpers";

// Hunspell's English dictionary, served by jsDelivr.
const DICTIONARY = "https://cdn.jsdelivr.net/npm/dictionary-en@3.2.0/index";

/** The router's blocker: it holds a move to another page while `when` says,
 *  and asks before a reload or a closed tab then too. */
const useRouterBlocker = (when: () => boolean): Blocker => {
  const blocker = useBlocker({ shouldBlockFn: when, enableBeforeUnload: when, withResolver: true });
  return {
    blocked: blocker.status === "blocked",
    proceed: () => blocker.proceed?.(),
    reset: () => blocker.reset?.(),
  };
};

/**
 * Hand the UI kit what it takes from Initiative: the mascot's toasts, the
 * phone's camera, the router's links and blocker, the phone's browser sheet,
 * the device's storage, the emoji data this app serves, the spelling
 * dictionary, the origins that are its own, how a person a field names is
 * drawn and the server's preview of a repeat's dates.
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
    useBlocker: useRouterBlocker,
    openExternal: (url) => openExternal(url),
    storage: { getItem: (key) => getItem(key), setItem: (key, value) => setItem(key, value) },
    emojibaseUrl: __EMOJIBASE_URL__,
    spellCheckDictionary: async () => {
      const [aff, dic] = await Promise.all(
        ["aff", "dic"].map(async (extension) => {
          const response = await fetch(`${DICTIONARY}.${extension}`);
          if (!response.ok) throw new Error("Failed to fetch dictionary files");
          return response.text();
        })
      );
      return { aff, dic };
    },
    isOwnOrigin: (url) => isOwnOrigin(url),
    // A person whose value carries only their id is drawn by their number.
    member: (person: UserValue & { id: number }) => ({
      ...toMember(person),
      name: getUserDisplayName(person, `#${person.id}`),
    }),
    previewRecurrence: (request) => previewRecurrence(request),
  });

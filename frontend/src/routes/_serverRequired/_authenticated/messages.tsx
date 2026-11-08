import { createFileRoute } from "@tanstack/react-router";

import { MyMessagesPage } from "@/pages/user/MyMessagesPage";

/**
 * Who the page should open a conversation with, as a URL handle —
 * `/messages?with=jordan1234`. It is what a person row links to, so somebody
 * you have never messaged is reachable in one click and the page decides what
 * that means: an open channel, or an offer to ask for one.
 */
interface MessagesSearch {
  with?: string;
  /**
   * Which thread to open, by conversation id — `/messages?thread=<uuid>`.
   *
   * A group is addressed this way because it has nothing else to be addressed
   * by: it has no name and no single handle, and the people on it are the only
   * thing it is, which is a set rather than an address. A pair keeps `with`,
   * where the handle is the point — it opens a conversation that may not exist
   * yet, which an id cannot do.
   */
  thread?: string;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/messages")({
  validateSearch: (search: Record<string, unknown>): MessagesSearch => {
    const handle = typeof search.with === "string" ? search.with.trim() : "";
    const thread = typeof search.thread === "string" ? search.thread.trim() : "";
    return { ...(handle ? { with: handle } : {}), ...(thread ? { thread } : {}) };
  },
  // No loader: a thread is read out of this device's own store, which the page
  // itself unlocks. There is nothing for the router to prefetch.
  component: MyMessagesPage,
});

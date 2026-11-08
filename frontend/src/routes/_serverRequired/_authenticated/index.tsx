import { createFileRoute } from "@tanstack/react-router";

import { type PageSearch, validatePage } from "@/lib/routeSearch";
import { HomePage } from "@/pages/my/home/HomePage";

/**
 * Home. There is deliberately no loader here.
 *
 * This route used to prefetch the task list under a hand-written key —
 * `["tasks", "me", "assigned", …]` — while the page reads it through
 * `useGlobalTasksTable`, which asks under the generated key for
 * `/api/v1/me/tasks`. The two never met: every visit paid for a request whose
 * answer nothing looked at, and because the key was not a request path the
 * offline cache would not persist it either. Each widget owns its own reads,
 * and which widgets there are is the reader's to say. `page` is the tasks
 * widget's table page.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/")({
  validateSearch: (search: Record<string, unknown>): PageSearch => ({
    page: validatePage(search.page),
  }),
  component: HomePage,
});

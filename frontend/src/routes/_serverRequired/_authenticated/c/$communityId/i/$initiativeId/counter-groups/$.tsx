import { createFileRoute, redirect } from "@tanstack/react-router";

import records from "@/api/generated/tools.json";

/** Counters moved into the Counters tool plug-in; these are its kinds. */
const movedKind = (key: string): string =>
  records.moved_kinds.find((kind) => kind.split(".")[0] === key) ?? key;
const GROUP = movedKind("counter_group");
const COUNTER = movedKind("counter");

/**
 * Where Counters' pages were before the plug-in: its list, a group (and the
 * group's settings) and a counter. Each goes to the same page under the
 * plug-in, so bookmarks and links written before still open.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$"
)({
  beforeLoad: ({ params }) => {
    const { communityId, initiativeId } = params;
    const [groupId, part, counterId] = (params._splat ?? "").split("/");
    const base = { communityId, initiativeId };
    if (groupId && part === "counter" && counterId) {
      throw redirect({
        to: "/c/$communityId/i/$initiativeId/t/$kind/$rowId",
        params: { ...base, kind: COUNTER, rowId: counterId },
        replace: true,
      });
    }
    if (groupId) {
      throw redirect({
        to: "/c/$communityId/i/$initiativeId/t/$kind/$rowId",
        params: { ...base, kind: GROUP, rowId: groupId },
        replace: true,
      });
    }
    throw redirect({
      to: "/c/$communityId/i/$initiativeId/t/$kind",
      params: { ...base, kind: GROUP },
      replace: true,
    });
  },
});

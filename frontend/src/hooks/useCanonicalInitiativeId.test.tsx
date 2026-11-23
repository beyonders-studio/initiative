/**
 * Correcting an address the entity disagrees with.
 *
 * The correction builds a destination out of the current location, and the
 * pieces of that location are not all strings: TanStack's `search` is the
 * parsed object and `hash` comes without its "#". Reaching for the wrong one
 * crashed the page it was trying to fix — and only ever on the mismatch path,
 * which is the branch nobody exercises by accident.
 */
import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { useCanonicalInitiativeId } from "./useCanonicalInitiativeId";

const ROUTE = "/c/$communityId/i/$initiativeId/projects/$projectId";
const PARAMS = { communityId: "3", initiativeId: "5", projectId: "1" };

/** A page whose entity says it belongs to `entityInitiativeId`. */
const pageFor = (entityInitiativeId: number | null | undefined) => () => {
  const id = useCanonicalInitiativeId(entityInitiativeId);
  return <div data-testid="resolved">{String(id)}</div>;
};

describe("useCanonicalInitiativeId", () => {
  it("rewrites the address to the entity's initiative, keeping its query and fragment", async () => {
    const { router } = renderPage(pageFor(7), {
      initialRoute: ROUTE,
      routeParams: PARAMS,
      routerSearch: { tab: "board" },
      routerHash: "tasks",
    });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/c/3/i/7/projects/1");
    });
    expect(router.state.location.search).toMatchObject({ tab: "board" });
    // Carried across as its own value — `hash` arrives without the "#", so a
    // correction that pasted it onto the path would lose it or bury it there.
    expect(router.state.location.hash).toBe("tasks");
  });

  it.each([
    ["agrees with", 5],
    ["is still loading for", undefined],
  ])("leaves the address alone while the entity %s it", async (_state, entityInitiativeId) => {
    const { router, getByTestId } = renderPage(pageFor(entityInitiativeId), {
      initialRoute: ROUTE,
      routeParams: PARAMS,
    });

    await waitFor(() => expect(getByTestId("resolved")).toHaveTextContent("5"));
    expect(router.state.location.pathname).toBe("/c/3/i/5/projects/1");
  });
});

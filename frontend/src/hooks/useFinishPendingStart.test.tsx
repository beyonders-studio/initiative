/**
 * Finishing a sign-up that waited for its address to be confirmed: on the
 * first signed-in load it lands where the page that sent them to sign up
 * asked, such as a plug-in's sign-in.
 */
import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { clearStart, freshAnswers, readPendingStart, savePendingStart } from "@/lib/startFlow";

import { useFinishPendingStart } from "./useFinishPendingStart";

const Finisher = () => {
  useFinishPendingStart();
  return null;
};

beforeEach(async () => {
  await clearStart();
});

describe("useFinishPendingStart", () => {
  it("lands on the page that sent them to sign up", async () => {
    const next = "/oauth/authorize?client_id=acme.hoard&state=s";
    await savePendingStart("new@example.com", freshAnswers("invite"), next);

    const { router } = renderPage(Finisher, {
      initialRoute: "/",
      auth: { user: buildUser({ email: "new@example.com" }), loading: false },
      communities: { communities: [], loading: false },
    });

    await waitFor(() => expect(router.state.location.href).toBe(next));
    expect(readPendingStart("new@example.com")).toBeNull();
  });
});

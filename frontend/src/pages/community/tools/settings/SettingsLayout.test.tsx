/**
 * Every tool's settings, through the route tree the app ships and each
 * route's own split component: the shared settings for the id the address
 * names, with the tool's own sections as tabs beside the shared ones.
 */
import { createRouter } from "@tanstack/react-router";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildContact, buildProject, buildWiki, readerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";
import { routeTree } from "@/routeTree.gen";
import type { TranslateFn } from "@/types/i18n";

const translate = i18n.t.bind(i18n) as TranslateFn;

const router = createRouter({ routeTree, context: buildRouterContext() });

/** A tool's settings route at its address (`section` after it), its component
 *  loaded from the chunk it is declared with, reading `entity` for the id 7. */
const renderSettings = async (
  component: unknown,
  segment: string,
  param: string,
  entity: object,
  section = "",
  initiative = "/i/$initiativeId"
) => {
  const Page = component as React.ComponentType & { preload?: () => Promise<unknown> };
  await Page.preload?.();
  server.use(communityHttp.get(`/${segment}/:id`, () => HttpResponse.json(entity)));
  return renderPage(Page, {
    initialRoute: `/c/$communityId${initiative}/${segment}/$${param}/settings${section}`,
    routeParams: { communityId: "1", initiativeId: "1", [param]: "7" },
  });
};

const wikiSettings = (entity: object = {}, section = "") =>
  renderSettings(
    router.routesById[
      "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings"
    ].options.component,
    "wikis",
    "wikiId",
    buildWiki({ id: 7, name: "House rules", initiative_id: 1, ...entity }),
    section
  );

const tab = (name: string) => screen.findByRole("tab", { name });

describe("a tool's settings route", () => {
  it("serves the contact its address names", async () => {
    await renderSettings(
      router.routesById[
        "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/contacts/$contactId/settings"
      ].options.component,
      "contacts",
      "contactId",
      buildContact({ id: 7, name: "Priya Shah", initiative_id: 1 })
    );

    expect(
      await screen.findByRole("tab", { name: translate("common:toolSettings.tabAccess") })
    ).toBeInTheDocument();
  });

  it("gives a project its own sections", async () => {
    await renderSettings(
      router.routesById[
        "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings"
      ].options.component,
      "projects",
      "projectId",
      buildProject({ id: 7, name: "Cake stall", initiative_id: 1 })
    );

    for (const key of ["tabTaskStatuses", "tabTaskTypes", "tabProperties"]) {
      expect(
        await screen.findByRole("tab", { name: translate(`projects:settings.${key}`) })
      ).toBeInTheDocument();
    }
  });

  it("opens a wiki on Details, each section a tab at its own address, its reading one too", async () => {
    const { router } = await wikiSettings();

    expect(await tab("Details")).toHaveAttribute("aria-selected", "true");
    for (const name of ["Access", "Advanced"]) expect(await tab(name)).toBeInTheDocument();
    await userEvent.click(await tab(translate("wikis:settings.tabReading")));
    // The section is an address, not a piece of component state.
    expect(router.state.location.pathname).toBe("/c/1/i/1/wikis/7/settings/reading");
    await act(() => router.history.back());
    await userEvent.click(await tab("Access"));
    expect(router.state.location.pathname).toBe("/c/1/i/1/wikis/7/settings/access");
  });

  it("lights the tab the address names", async () => {
    await wikiSettings({}, "/advanced");

    expect(await tab("Advanced")).toHaveAttribute("aria-selected", "true");
  });

  it("keeps access and an empty advanced section out of the bar for a reader", async () => {
    // Advanced is a tool's extra operations plus deletion. A reader of a tool
    // that declares neither has no advanced section to visit.
    await wikiSettings({ can: readerCan() });

    expect(await tab("Details")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Access" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Advanced" })).not.toBeInTheDocument();
  });

  it("addresses a community-level calendar at its community route", async () => {
    await renderSettings(
      router.routesById[
        "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/settings"
      ].options.component,
      "calendars",
      "calendarId",
      { ...buildWiki({ id: 7, name: "Feast days" }), initiative_id: null, color: "#6366f1" },
      "",
      ""
    );

    expect(await tab("Details")).toHaveAttribute("aria-selected", "true");
  });
});

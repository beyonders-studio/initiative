/**
 * Every tool's settings, through the route tree the app ships and each
 * route's own split component: the shared settings for the id the address
 * names, with the tool's own sections as tabs beside the shared ones.
 */
import { createRouter } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildContact, buildProject, buildWiki } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";
import { routeTree } from "@/routeTree.gen";
import type { TranslateFn } from "@/types/i18n";

const translate = i18n.t.bind(i18n) as TranslateFn;

const router = createRouter({ routeTree, context: buildRouterContext() });

/** A tool's settings route at its address, its component loaded from the
 *  chunk it is declared with, reading `entity` for the id 7. */
const renderSettings = async (
  component: unknown,
  segment: string,
  param: string,
  entity: { name: string }
) => {
  const Page = component as React.ComponentType & { preload?: () => Promise<unknown> };
  await Page.preload?.();
  server.use(communityHttp.get(`/${segment}/:id`, () => HttpResponse.json(entity)));
  renderPage(Page, {
    initialRoute: `/c/$communityId/i/$initiativeId/${segment}/$${param}/settings`,
    routeParams: { communityId: "1", initiativeId: "1", [param]: "7" },
  });
};

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

  it("gives a wiki its reading section", async () => {
    await renderSettings(
      router.routesById[
        "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings"
      ].options.component,
      "wikis",
      "wikiId",
      buildWiki({ id: 7, name: "House rules", initiative_id: 1 })
    );

    expect(
      await screen.findByRole("tab", { name: translate("wikis:settings.tabReading") })
    ).toBeInTheDocument();
  });
});

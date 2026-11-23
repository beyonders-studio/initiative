/**
 * The panel every tool drops on its page.
 *
 * What is worth pinning is the derivation, because that is what lets a tenth
 * tool need no wiring: which thing the links belong to, which tool's cache a
 * write refreshes, and the one case where the panel takes itself out of the
 * way.
 */
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";

const noLinks = () => server.use(communityHttp.get("/relationships/", () => HttpResponse.json([])));

describe("ToolRelationsPanel", () => {
  it("names itself after the CHILD when the links are the child's", async () => {
    // An event's links are the event's; the calendar only answers for them.
    noLinks();
    renderPage(
      () => (
        <ToolRelationsPanel
          tool={Tool.calendar}
          entity={{ id: 3, initiative_id: 7 }}
          target={{ type: SearchEntityType.calendar_event, id: 42 }}
          canEdit
        />
      ),
      { initialRoute: "/c/1" }
    );

    expect(await screen.findByText(/Link the task this event is for/)).toBeInTheDocument();
  });

  // A community calendar belongs to no initiative, and every link is made inside
  // one — so there is nothing to offer but a refusal; and nothing is drawn while
  // the row is still arriving.
  it.each([
    [Tool.calendar, { id: 3, initiative_id: null }],
    [Tool.dashboard, undefined],
  ])("takes itself out of the way where a link cannot be made (%s)", (tool, entity) => {
    noLinks();
    const { container } = renderPage(
      () => <ToolRelationsPanel tool={tool} entity={entity} canEdit />,
      { initialRoute: "/c/1" }
    );

    expect(container).toBeEmptyDOMElement();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildContact, buildProject, buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type ContactRead,
  EndpointKind,
  type RelatedEnd,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";

import { ContactDetailPage } from "./ContactDetailPage";

let nextId = 100;

/** One of the contact's links, from the contact's side. */
const link = (
  other: Partial<RelatedEnd> & Pick<RelatedEnd, "type" | "title">,
  relationship_type: RelationshipType = RelationshipType.related_to,
  direction: "inbound" | "outbound" = "outbound"
): RelationshipRead => ({
  id: nextId++,
  relationship_type,
  direction,
  provenance: "manual",
  confidence: null,
  created_by: 1,
  created_at: "2026-09-01T00:00:00Z",
  other: {
    id: nextId,
    initiative_id: 1,
    updated_at: null,
    tool: null,
    tool_id: null,
    tool_title: null,
    image_urls: [],
    icon: null,
    color: null,
    file_type: null,
    mime_type: null,
    original_filename: null,
    smart_link_url: null,
    handle: null,
    is_open: null,
    starts_at: null,
    ...other,
  },
});

const showContact = (contact: ContactRead, links: RelationshipRead[] = []) => {
  server.use(
    communityHttp.get("/contacts/:contactId", () => HttpResponse.json(contact)),
    communityHttp.get("/relationships/", () => HttpResponse.json(links))
  );
  return renderPage(ContactDetailPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/contacts/$contactId",
    routeParams: { communityId: "1", initiativeId: "1", contactId: String(contact.id) },
  });
};

describe("a contact's page", () => {
  it("reaches them in one tap and shows where things stand", async () => {
    showContact(
      buildContact({
        id: 5,
        name: "Priya Shah",
        phones: [{ label: "Mobile", value: "+1 555 0100 x12" }],
        emails: [{ label: "Work", value: "priya@example.com" }],
      }),
      [
        link({ type: EndpointKind.task, title: "Send the deposit", is_open: true }),
        link({ type: EndpointKind.task, title: "Sign the contract", is_open: false }),
        link({
          type: EndpointKind.calendar_event,
          title: "Tasting",
          starts_at: "2999-06-01T17:00:00Z",
        }),
        link({
          type: EndpointKind.calendar_event,
          title: "First call",
          starts_at: "2001-06-01T17:00:00Z",
        }),
      ]
    );

    expect(await screen.findByRole("link", { name: "+1 555 0100 x12" })).toHaveAttribute(
      "href",
      "tel:+15550100;ext=12"
    );
    expect(screen.getByRole("link", { name: "priya@example.com" })).toHaveAttribute(
      "href",
      "mailto:priya@example.com"
    );

    const open = await screen.findByRole("list", { name: "Open tasks" });
    expect(within(open).getByText("Send the deposit")).toBeInTheDocument();
    expect(within(open).queryByText("Sign the contract")).not.toBeInTheDocument();
    const upcoming = screen.getByRole("list", { name: "Coming up" });
    expect(within(upcoming).getByText("Tasting")).toBeInTheDocument();
    expect(within(upcoming).queryByText("First call")).not.toBeInTheDocument();
  });

  it("lists an organization's people", async () => {
    showContact(buildContact({ id: 6, name: "Lakeside Lodge", is_organization: true }), [
      link(
        { type: EndpointKind.contact, id: 9, title: "Sam Ortiz" },
        RelationshipType.part_of,
        "inbound"
      ),
    ]);

    const people = await screen.findByRole("list", { name: "People" });
    expect(within(people).getByRole("link", { name: /Sam Ortiz/ })).toHaveAttribute(
      "href",
      "/c/1/i/1/contacts/9"
    );
  });

  it("links a new task to the contact", async () => {
    const sent: RelationshipCreate[] = [];
    server.use(
      http.get("/api/v1/me/projects", () =>
        HttpResponse.json({
          items: [buildProject({ id: 3, name: "Wedding", initiative_id: 1 })],
          total_count: 1,
          page: 1,
          page_size: 25,
          has_next: false,
        })
      ),
      communityHttp.post("/tasks/", () => HttpResponse.json(buildTask({ id: 77 }))),
      communityHttp.post("/relationships/", async ({ request }) => {
        const body = (await request.json()) as RelationshipCreate;
        sent.push(body);
        return HttpResponse.json(
          link({ type: EndpointKind.task, id: 77, title: "Send the deposit", tool: Tool.project })
        );
      })
    );
    const user = userEvent.setup();
    showContact(buildContact({ id: 5, name: "Priya Shah" }));

    await user.click(await screen.findByRole("button", { name: "New task" }));
    await user.click(await screen.findByRole("button", { name: "Wedding" }));
    await user.type(screen.getByLabelText("Title"), "Send the deposit");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({
      source: { type: EndpointKind.contact, id: 5 },
      relationship_type: RelationshipType.related_to,
      target: { type: EndpointKind.task, id: 77 },
    });
  });
});

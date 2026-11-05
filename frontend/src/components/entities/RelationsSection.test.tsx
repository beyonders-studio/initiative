/**
 * Everything connected to one thing.
 *
 * One request answers for every heading, so what is worth asserting is the
 * sorting: that a directional relation lands under the right one of its two
 * headings, that a heading with nothing under it is not drawn at all, and that a
 * link nobody asserted is not offered as one to take back.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildSearchSuggestion,
  buildUser,
  buildUserSummary,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  EndpointKind,
  type RelationshipRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";

/**
 * Sigma draws the graph to a WebGL canvas, which jsdom has none of. The renderer
 * is stubbed so the rest of the picture — the controls around it, the region it
 * is drawn in, the key to its colours — is still the code under test. What the
 * canvas itself puts on screen is not a thing a DOM test can see either way.
 */
vi.mock("@react-sigma/core", () => ({
  SigmaContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="sigma">{children}</div>
  ),
  useSigma: () => ({
    getGraph: () => ({
      order: 0,
      setNodeAttribute: () => {},
      removeNodeAttribute: () => {},
    }),
    viewportToGraph: () => ({ x: 0, y: 0 }),
  }),
  useRegisterEvents: () => () => {},
}));

// The WebGL machinery, stubbed at the seam rather than by faking a graphics
// card: these draw to a canvas, and a canvas draws nothing jsdom can be asked
// about.
vi.mock("@sigma/node-image", () => ({
  createNodeImageProgram: () => class {},
  NodeImageProgram: class {},
}));
vi.mock("sigma/utils", () => ({ animateNodes: () => () => {} }));
vi.mock("sigma/rendering", () => ({ drawDiscNodeLabel: () => {} }));

/**
 * The upload itself, stubbed where the app calls it: jsdom's multipart bodies
 * are not something MSW can read back, and what is under test is what the
 * panel does with the file that comes back.
 */
const uploadFile = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/files/files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/files/files")>()),
  uploadFile: uploadFile,
}));

import { RelationsSection } from "./RelationsSection";

let nextId = 1;

/** Everything a far end of a link carries and none of these cases vary. */
const farEnd = {
  initiative_id: null,
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
};

const row = (
  relationship_type: RelationshipRead["relationship_type"],
  direction: "inbound" | "outbound",
  title: string,
  provenance = "manual"
): RelationshipRead => ({
  id: nextId++,
  relationship_type,
  direction,
  provenance,
  confidence: null,
  created_by: 1,
  created_at: "2026-09-01T00:00:00Z",
  other: {
    ...farEnd,
    type: SearchEntityType.task,
    id: nextId,
    title,
    initiative_id: 3,
    tool: Tool.project,
    tool_id: 1,
  },
});

/** A dependency whose far end knows whether it is finished. */
const blocker = (title: string, isOpen: boolean): RelationshipRead => {
  const built = row("depends_on", "outbound", title);
  return { ...built, other: { ...built.other, is_open: isOpen } };
};

const tagEnd = { ...farEnd, type: SearchEntityType.tag, id: 99, title: "combat", color: "#ff0000" };

type Layout = "tiles" | "rows" | "carousel" | "graph";

/** The section itself, however this case has already answered the endpoint. */
const mount = (canEdit = true, defaultLayout: Layout = "tiles") =>
  renderPage(
    () => (
      <RelationsSection
        entity={{ type: SearchEntityType.task, id: 1 }}
        initiativeId={3}
        canEdit={canEdit}
        defaultLayout={defaultLayout}
      />
    ),
    { initialRoute: "/c/1" }
  );

const renderSection = (
  rows: RelationshipRead[],
  canEdit = true,
  defaultLayout: Layout = "tiles"
) => {
  server.use(communityHttp.get("/relationships/", () => HttpResponse.json(rows)));
  return mount(canEdit, defaultLayout);
};

/**
 * The section for somebody who may make files in its initiative, so the
 * dialog may offer an upload. Records what was uploaded and linked.
 */
const mountUploader = ({ canCreateFiles = true, canViewFiles = true } = {}) => {
  const user = buildUser();
  const writes: { links: unknown[] } = { links: [] };
  uploadFile.mockReset();
  uploadFile.mockResolvedValue({ id: 77, name: "Floor plan" });
  server.use(
    communityHttp.get("/relationships/", () => HttpResponse.json([])),
    communityHttp.get("/initiatives/", () =>
      HttpResponse.json([
        buildInitiative({
          id: 3,
          can: initiativeCan({
            view: canViewFiles ? [Tool.file] : [],
            create: canCreateFiles ? [Tool.file] : [],
          }),
        }),
      ])
    ),
    communityHttp.put("/files/:id/grants", () => HttpResponse.json({})),
    communityHttp.post("/relationships/", async ({ request }) => {
      const body = await request.json();
      writes.links.push(body);
      return HttpResponse.json({
        ...row("attached", "outbound", "Floor plan"),
        other: { ...farEnd, type: SearchEntityType.file, id: 77, title: "Floor plan" },
      });
    })
  );
  renderPage(
    () => (
      <RelationsSection entity={{ type: SearchEntityType.task, id: 1 }} initiativeId={3} canEdit />
    ),
    { initialRoute: "/c/1", auth: { user } }
  );
  return writes;
};

const aFile = (name = "floor-plan.pdf") => new File(["%PDF"], name, { type: "application/pdf" });

/** The block a heading names, so a link can be asserted to be filed under it. */
const sectionNamed = async (name: string) =>
  (await screen.findByRole("heading", { name })).closest("section") as HTMLElement;

/** A label, which is fetched with everything else and drawn by no heading. */
const tagRow = (): RelationshipRead => ({
  ...row("tagged_with", "outbound", "combat"),
  other: { ...tagEnd },
});

describe("RelationsSection", () => {
  it("sorts the two sides of a dependency under their own headings", async () => {
    renderSection([
      row("depends_on", "outbound", "Waiting on this"),
      row("depends_on", "inbound", "Held up by me"),
    ]);

    const blockedBy = await sectionNamed("Blocked by");
    const blocks = await sectionNamed("Blocking");

    expect(within(blockedBy).getByText("Waiting on this")).toBeInTheDocument();
    expect(within(blocks).getByText("Held up by me")).toBeInTheDocument();
  });

  it("takes a symmetric link whichever way it runs", async () => {
    renderSection([row("attached", "inbound", "Attached from the far side")]);

    const attached = await sectionNamed("Attached");
    expect(within(attached).getByText("Attached from the far side")).toBeInTheDocument();
  });

  it("draws no heading for a relation nothing has", async () => {
    renderSection([row("attached", "outbound", "Only this")]);

    await screen.findByText("Only this");
    expect(screen.queryByRole("heading", { name: "Blocked by" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Part of" })).not.toBeInTheDocument();
  });

  // Counting the answer rather than what is drawn reported "some" over an
  // empty panel, because a label comes back with everything else and no
  // heading here draws it.
  it.each([
    ["nothing is connected", [] as RelationshipRead[]],
    ["nothing it shows is", [tagRow()]],
  ])("says so plainly when %s", async (_label, rows) => {
    renderSection(rows);

    expect(await screen.findByText(/Nothing linked yet\./)).toBeInTheDocument();
  });

  it("does not offer to unlink something read out of a body", async () => {
    // A `references` edge is withdrawn by editing the words that made it, so
    // there is nothing here to click.
    renderSection([row("references", "inbound", "A page that mentions this", "content")]);

    const section = await sectionNamed("Mentioned in");
    expect(within(section).getByText("A page that mentions this")).toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: /A page that mentions this/ })
    ).not.toBeInTheDocument();
  });

  it("opens the add dialog on the thing, not on a classification", async () => {
    // Nobody opens this thinking "part_of". The picker is the only field until
    // something is picked, so the abstract question is never the price of entry.
    const user = userEvent.setup();
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("combobox", { name: "Thing" })).toBeEnabled();
    expect(within(dialog).queryByLabelText("How the two relate")).not.toBeInTheDocument();
  });

  it("opens the way the surface asked, and offers the other ways", async () => {
    const user = userEvent.setup();
    renderSection([row("attached", "outbound", "Only this")], true, "rows");

    await screen.findByText("Only this");
    await user.click(screen.getByRole("button", { name: "How to show these" }));
    const menu = await screen.findByRole("menu");
    for (const name of ["Tiles", "List", "Carousel", "Graph"]) {
      expect(within(menu).getByRole("menuitem", { name })).toBeInTheDocument();
    }
  });

  it("shows one shelf in a carousel, with each link saying what it is", async () => {
    // No heading per kind of link: a carousel is pushed along, so what a link
    // says rides on its own card.
    renderSection(
      [row("attached", "outbound", "A brief"), row("depends_on", "outbound", "A blocker")],
      true,
      "carousel"
    );

    await screen.findByText("A brief");
    expect(screen.queryByRole("heading", { name: "Attached" })).not.toBeInTheDocument();
    expect(screen.getByText("Attached")).toBeInTheDocument();
    expect(screen.getByText("Blocked by")).toBeInTheDocument();
  });

  it("draws the picture with a key to what its colours mean", async () => {
    // The graph itself is a canvas, so what can be asserted here is the frame
    // around it: that it was drawn for these links, and that a reader is told
    // which colour is which.
    renderSection(
      [row("attached", "outbound", "A brief"), row("depends_on", "inbound", "Waiting on me")],
      true,
      "graph"
    );

    expect(await screen.findByRole("region", { name: /2 things/ })).toBeInTheDocument();
    expect(screen.getByText("Attached")).toBeInTheDocument();
    expect(screen.getByText("Blocking")).toBeInTheDocument();
    // Nothing it has no link of: a key listing every heading would say nothing.
    expect(screen.queryByText("Part of")).not.toBeInTheDocument();
  });

  it("walks further out when asked, and then in one request", async () => {
    // One hop is the list the section already holds. Further out is the whole
    // walk in one answer, however many things the first hop found.
    const user = userEvent.setup();
    const listed: string[] = [];
    const walked: URLSearchParams[] = [];
    const near = row("attached", "outbound", "A brief");
    server.use(
      communityHttp.get("/relationships/", ({ request }) => {
        listed.push(new URL(request.url).searchParams.get("entity") ?? "");
        return HttpResponse.json([near]);
      }),
      communityHttp.get("/relationships/neighbourhood", ({ request }) => {
        walked.push(new URL(request.url).searchParams);
        const far = { ...near.other, id: 500, title: "Two out" };
        return HttpResponse.json({
          nodes: [
            { end: near.other, depth: 1 },
            { end: far, depth: 2 },
          ],
          edges: [
            {
              id: near.id,
              relationship_type: "attached",
              anchor: { type: "task", id: 1 },
              other: { type: near.other.type, id: near.other.id },
              direction: "outbound",
              provenance: "manual",
            },
            {
              id: 9000,
              relationship_type: "related_to",
              anchor: { type: near.other.type, id: near.other.id },
              other: { type: far.type, id: far.id },
              direction: "outbound",
              provenance: "manual",
            },
          ],
        });
      })
    );
    mount(true, "graph");

    await screen.findByRole("region", { name: /1 thing/ });
    expect(walked).toHaveLength(0);
    expect(listed.every((entity) => entity === "task:1")).toBe(true);

    await user.click(screen.getByRole("button", { name: "2 hops" }));
    expect(await screen.findByRole("region", { name: /2 things/ })).toBeInTheDocument();
    expect(walked).toHaveLength(1);
    expect(walked[0]?.get("entity")).toBe("task:1");
    expect(walked[0]?.get("hops")).toBe("2");
    expect(walked[0]?.get("include_tags")).toBe("false");
    // Nothing was asked of the neighbour itself.
    expect(listed.every((entity) => entity === "task:1")).toBe(true);
  });

  it("keeps the first hop up when the walk further out fails", async () => {
    // The list already holds the thing's own links, so a failed walk is no
    // reason to draw nothing, nor to take away the way back to one hop.
    const user = userEvent.setup();
    server.use(
      communityHttp.get("/relationships/", () =>
        HttpResponse.json([row("attached", "outbound", "A brief")])
      ),
      communityHttp.get("/relationships/neighbourhood", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    );
    mount(true, "graph");

    await screen.findByRole("region", { name: /1 thing/ });
    await user.click(screen.getByRole("button", { name: "2 hops" }));

    expect(
      await screen.findByText("Couldn't look further out, so this shows only direct links.")
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /1 thing/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 hop" })).toBeInTheDocument();
  });

  it("leaves labels out of the graph until asked, and out of the walk", async () => {
    // A tag is carried by everything that carries it, so walking through one
    // reaches most of the community in a hop. Filtering it when drawing would
    // still have paid for the walk.
    const user = userEvent.setup();
    renderSection([row("attached", "outbound", "A brief"), tagRow()], true, "graph");

    // One of the two links is a label, and it is not in the picture.
    expect(await screen.findByRole("region", { name: /1 thing/ })).toBeInTheDocument();
    expect(screen.queryByText("Tagged")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show tags" }));
    expect(await screen.findByRole("region", { name: /2 things/ })).toBeInTheDocument();
    expect(screen.getByText("Tagged")).toBeInTheDocument();
  });

  it("says which project a link is in, when its name does not", async () => {
    // Six projects run from one template hold six tasks called "Do a thing".
    // The card has to say which, or it says nothing at all.
    const link = row("attached", "outbound", "Do a thing");
    renderSection([{ ...link, other: { ...link.other, tool_title: "Harvest" } }]);

    const section = await sectionNamed("Attached");
    expect(within(section).getByText(/Harvest/)).toBeInTheDocument();
  });

  it("says where each thing the picker offers lives", async () => {
    const user = userEvent.setup();
    // Two tasks of the same name, in different projects of one initiative.
    const offered = (entity_id: number, tool_id: number, tool_title: string) =>
      buildSearchSuggestion({
        entity_type: SearchEntityType.task,
        entity_id,
        title: "Do a thing",
        tool: Tool.project,
        tool_id,
        tool_title,
        initiative_id: 3,
        initiative_name: "Farmhands",
      });
    server.use(
      communityHttp.get("/search/recent", () =>
        HttpResponse.json([offered(11, 1, "Harvest"), offered(12, 2, "Winterhold")])
      )
    );
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "Thing" }));

    expect(await screen.findByText("Harvest")).toBeInTheDocument();
    expect(screen.getByText("Winterhold")).toBeInTheDocument();
    // The picker is already confined to one initiative, so naming it on every
    // row would be the same word twice over.
    expect(screen.queryByText(/Farmhands/)).not.toBeInTheDocument();
  });

  it("offers no way in at all to a reader who may not edit", async () => {
    renderSection([row("attached", "outbound", "Only this")], false);

    await screen.findByText("Only this");
    expect(screen.queryByRole("button", { name: "Add link" })).not.toBeInTheDocument();
  });

  it("says how far along a linked project is", async () => {
    // The card carries what the thing is doing now, not what it was called
    // when somebody linked it — so a project reads as its work.
    const built = row("attached", "outbound", "Marquee logistics");
    const project = {
      ...built,
      other: { ...built.other, type: SearchEntityType.project, id: 7 },
    };
    server.use(
      communityHttp.post("/smart-chips/", () =>
        HttpResponse.json({
          items: [
            {
              ref: "project:7:progress",
              entity_type: SearchEntityType.project,
              aspect: "progress",
              text: "1 / 3",
              title: null,
              tone: "neutral",
              color: null,
              date: null,
              number: null,
            },
          ],
        })
      )
    );
    renderSection([project]);

    expect(await screen.findByText("1 / 3")).toBeInTheDocument();
  });

  it("names itself after the thing it is about", async () => {
    // "Relations" is a word about the data model. A task has connections.
    renderSection([]);

    expect(await screen.findByRole("heading", { name: "Connections" })).toBeInTheDocument();
  });

  it("says how many blockers are still open, not how many there ever were", async () => {
    // A bare count outlives the work it describes, which is most of why the
    // heading stopped meaning anything.
    renderSection([blocker("Still going", true), blocker("Finished", false)]);

    const section = await sectionNamed("Blocked by");
    expect(within(section).getByText("1 of 2 still open")).toBeInTheDocument();
  });

  it("does not offer four ways of looking at nothing", async () => {
    renderSection([]);

    await screen.findByText(/Nothing linked yet\./);
    expect(screen.queryByRole("button", { name: "How to show these" })).not.toBeInTheDocument();
  });

  it("offers the ways of looking once there is something to look at", async () => {
    renderSection([row("attached", "outbound", "Something")]);

    await screen.findByText("Something");
    expect(screen.getByRole("button", { name: "How to show these" })).toBeInTheDocument();
  });

  it("writes the link out as a sentence naming both ends", async () => {
    const user = userEvent.setup();
    server.use(
      communityHttp.get("/search/recent", () =>
        HttpResponse.json([
          buildSearchSuggestion({
            entity_type: SearchEntityType.file,
            entity_id: 11,
            title: "Harvest",
            initiative_id: 3,
          }),
        ])
      )
    );
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "Thing" }));
    await user.click(await screen.findByText("Harvest"));

    // Both nouns are on screen, and the verb between them is a control.
    expect(within(dialog).getByText("This task")).toBeInTheDocument();
    const verb = within(dialog).getByRole("combobox", { name: "How the two relate" });
    // Never a dependency on somebody's behalf — that claim is theirs to make.
    expect(verb).not.toHaveTextContent("is blocked by");
  });

  it("draws a linked person by their name, and opens their profile", async () => {
    // A person is reached by their own profile, outside the community, rather
    // than by a page in it.
    const link = row("related_to", "outbound", "Jane Accountant");
    renderSection([
      {
        ...link,
        other: {
          ...farEnd,
          type: EndpointKind.user,
          id: 42,
          title: "Jane Accountant",
          handle: "jane0042",
        },
      },
    ]);

    const section = await sectionNamed("See also");
    expect(within(section).getByRole("link", { name: /Jane Accountant/ })).toHaveAttribute(
      "href",
      "/u/jane0042"
    );
  });

  it("links a member found on the Members tab, from the whole roster", async () => {
    // Who a link names need not be able to open the thing it is on, so the
    // search is not narrowed to the task.
    const user = userEvent.setup();
    const searched: URLSearchParams[] = [];
    const linked: unknown[] = [];
    server.use(
      communityHttp.get("/users/search", ({ request }) => {
        searched.push(new URL(request.url).searchParams);
        const items = [buildUserSummary({ id: 42, display_name: "Jane Accountant" })];
        return HttpResponse.json({
          items,
          total_count: items.length,
          page: 1,
          page_size: 25,
          has_next: false,
          has_prev: false,
        });
      }),
      communityHttp.post("/relationships/", async ({ request }) => {
        linked.push(await request.json());
        return HttpResponse.json(row("related_to", "outbound", "Jane Accountant"));
      })
    );
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("tab", { name: "Members" }));
    await user.click(within(dialog).getByRole("combobox", { name: "Person" }));
    await user.click(await screen.findByText("Jane Accountant"));

    // A person is related to the task, never attached to it on their behalf.
    const verb = within(dialog).getByRole("combobox", { name: "How the two relate" });
    expect(verb).toHaveTextContent("is related to");
    await user.click(within(dialog).getByRole("button", { name: "Add link" }));

    await waitFor(() => expect(linked).toHaveLength(1));
    expect(linked[0]).toMatchObject({
      source: { type: "task", id: 1 },
      relationship_type: "related_to",
      target: { type: "user", id: 42 },
    });
    expect(searched.length).toBeGreaterThan(0);
    for (const params of searched) {
      expect(params.has("tool")).toBe(false);
      expect(params.has("resource_id")).toBe(false);
    }
  });

  describe("uploading a file to link", () => {
    it("makes the upload a file and links it, in one step", async () => {
      const user = userEvent.setup();
      const writes = mountUploader();

      await user.click(await screen.findByRole("button", { name: "Add link" }));
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByRole("button", { name: "Choose a file" });
      const input = dialog.querySelector('input[type="file"]') as HTMLInputElement;
      await user.upload(input, aFile());

      // Named after the file until somebody names it, and said as a sentence
      // like any other far end — attached, never a dependency.
      expect(within(dialog).getByLabelText("Name")).toHaveValue("floor-plan");
      expect(within(dialog).getByText("floor-plan.pdf")).toBeInTheDocument();
      const verb = within(dialog).getByRole("combobox", { name: "How the two relate" });
      expect(verb).toHaveTextContent("is attached to");

      await user.click(within(dialog).getByRole("button", { name: "Upload and link" }));

      await waitFor(() => expect(writes.links).toHaveLength(1));
      expect(uploadFile).toHaveBeenCalledTimes(1);
      expect(uploadFile.mock.calls[0]?.[1]).toMatchObject({
        name: "floor-plan",
        initiative_id: 3,
      });
      expect(writes.links[0]).toMatchObject({
        source: { type: "task", id: 1 },
        relationship_type: "attached",
        target: { type: "file", id: 77 },
      });
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("goes back to the picker when the file is put down", async () => {
      const user = userEvent.setup();
      mountUploader();

      await user.click(await screen.findByRole("button", { name: "Add link" }));
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByRole("button", { name: "Choose a file" });
      await user.upload(dialog.querySelector('input[type="file"]') as HTMLInputElement, aFile());
      await user.click(within(dialog).getByRole("button", { name: "Pick something else instead" }));

      expect(within(dialog).getByRole("combobox", { name: "Thing" })).toBeInTheDocument();
      expect(within(dialog).queryByText("floor-plan.pdf")).not.toBeInTheDocument();
    });

    it("opens the dialog holding a file dropped on the section", async () => {
      mountUploader();

      const heading = await screen.findByRole("heading", { name: "Connections" });
      const section = heading.closest("[data-state]") as HTMLElement;
      // The create flag arrives with the initiative list; until then there is
      // nowhere to drop.
      await waitFor(() => {
        fireEvent.dragEnter(section, { dataTransfer: { types: ["Files"], files: [] } });
        expect(screen.getByText("Drop to upload and link")).toBeInTheDocument();
      });
      fireEvent.drop(section, { dataTransfer: { types: ["Files"], files: [aFile()] } });

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("floor-plan.pdf")).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: "Upload and link" })).toBeEnabled();
    });

    it.each([
      ["may not make files here", { canCreateFiles: false }],
      ["does not have files here", { canViewFiles: false }],
    ])("does not offer an upload to somebody who %s", async (_label, access) => {
      const user = userEvent.setup();
      mountUploader(access);

      await user.click(await screen.findByRole("button", { name: "Add link" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByRole("combobox", { name: "Thing" })).toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Choose a file" })
      ).not.toBeInTheDocument();
    });

    it("links the file it already uploaded when the link is tried again", async () => {
      // The upload landed and the link did not. Trying again must not leave a
      // second copy of the file behind.
      const user = userEvent.setup();
      const writes = mountUploader();
      let refused = false;
      server.use(
        communityHttp.post("/relationships/", async ({ request }) => {
          if (!refused) {
            refused = true;
            return HttpResponse.json({ detail: "nope" }, { status: 500 });
          }
          writes.links.push(await request.json());
          return HttpResponse.json(row("attached", "outbound", "Floor plan"));
        })
      );

      await user.click(await screen.findByRole("button", { name: "Add link" }));
      const dialog = await screen.findByRole("dialog");
      await within(dialog).findByRole("button", { name: "Choose a file" });
      await user.upload(dialog.querySelector('input[type="file"]') as HTMLInputElement, aFile());
      const submit = within(dialog).getByRole("button", { name: "Upload and link" });
      await user.click(submit);
      await waitFor(() => expect(refused).toBe(true));
      await waitFor(() => expect(submit).toBeEnabled());
      await user.click(submit);

      await waitFor(() => expect(writes.links).toHaveLength(1));
      expect(uploadFile).toHaveBeenCalledTimes(1);
    });
  });
});

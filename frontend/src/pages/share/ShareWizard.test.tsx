import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative, buildProject, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { useCommunities } from "@/hooks/useCommunities";
import type { ReceivedShare } from "@/lib/share/pendingShare";

const communities = [
  buildCommunity({ id: 3, name: "Anvil Club" }),
  buildCommunity({ id: 8, name: "Bellwether" }),
];
let shownCommunities = communities;

// Partial: the render helper reaches for ``CommunityContext`` from this module.
vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () =>
    ({ communities: shownCommunities }) as unknown as ReturnType<typeof useCommunities>,
}));

// Held still across renders: the steps key effects off the identity of what
// these return.
const twoInitiatives = {
  initiatives: [
    buildInitiative({ id: 4, name: "Spring Play" }),
    buildInitiative({ id: 5, name: "Summer Play" }),
  ],
  isLoading: false,
};
const oneInitiative = {
  initiatives: [buildInitiative({ id: 4, name: "Spring Play" })],
  isLoading: false,
};
let initiativesResult = twoInitiatives;
const creatableFor = vi.fn();
vi.mock("@/hooks/useInitiativeAccess", () => ({
  communityMayWriteContent: () => true,
  communityMayAuthorTools: () => true,
  useCreatableInitiatives: (tool: unknown, communityId: unknown) => {
    creatableFor(tool, communityId);
    return initiativesResult;
  },
}));

const projectsResult = {
  data: {
    items: [buildProject({ id: 6, name: "Props", initiative_id: 4 })],
    has_next: false,
  },
};
vi.mock("@/hooks/useProjects", () => ({
  useGlobalProjects: () => projectsResult,
}));

const stored = vi.hoisted(() => new Map<string, string>());
vi.mock("@/lib/storage", () => ({
  getItem: (key: string) => stored.get(key) ?? null,
  setItem: (key: string, value: string) => stored.set(key, value),
  removeItem: (key: string) => stored.delete(key),
}));

const landShare = vi.fn(async (_input: unknown) => "/c/3/i/4/projects/6/tasks/77");
vi.mock("@/lib/share/landShare", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/share/landShare")>()),
  landShare: (input: unknown) => landShare(input),
}));

import { ShareWizard } from "./ShareWizard";

const share: ReceivedShare = {
  id: 1,
  title: "A great #article",
  texts: ["https://example.com/article"],
  files: [],
  opened: true,
};

const PDF = { uri: "/cache/minutes.pdf", name: "minutes.pdf", mimeType: "application/pdf" };
const PNG = { uri: "/cache/cat.png", name: "cat.png", mimeType: "image/png" };

const renderWizard = (onDone = vi.fn(), shared: ReceivedShare = share) => {
  renderWithProviders(<ShareWizard share={shared} onDone={onDone} />, {
    auth: { user: buildUser() },
  });
  return onDone;
};

beforeEach(() => {
  shownCommunities = communities;
  initiativesResult = twoInitiatives;
  stored.clear();
  vi.clearAllMocks();
});

describe("ShareWizard", () => {
  it("shows what was shared and asks what it should become", async () => {
    renderWizard();

    expect(await screen.findByText("What should this become?")).toBeInTheDocument();
    // The title it will be given, already fit to be a name.
    expect(screen.getByText("A great article")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/article")).toBeInTheDocument();
    for (const kind of ["Task", "Document", "Post"]) {
      expect(screen.getByText(kind)).toBeInTheDocument();
    }
    // Nothing to upload in a link.
    expect(screen.queryByText("File")).not.toBeInTheDocument();
  });

  it("offers every kind for a share of pictures", async () => {
    renderWizard(vi.fn(), { ...share, title: "", texts: [], files: [PNG] });

    for (const kind of ["Task", "Document", "File", "Post"]) {
      expect(await screen.findByText(kind)).toBeInTheDocument();
    }
  });

  it("offers only an upload for a share that is only a PDF", async () => {
    renderWizard(vi.fn(), { ...share, title: "", texts: [], files: [PDF] });

    expect(await screen.findByText("File")).toBeInTheDocument();
    for (const kind of ["Task", "Document", "Post"]) {
      expect(screen.queryByText(kind)).not.toBeInTheDocument();
    }
  });

  it("uploads each file under the name given it", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    landShare.mockResolvedValueOnce("/c/3/i/4/files");
    const user = userEvent.setup();
    const onDone = renderWizard(vi.fn(), { ...share, texts: [], files: [PDF, PNG] });

    await user.click(await screen.findByText("File"));
    expect(creatableFor).toHaveBeenCalledWith("file", 3);

    const name = await screen.findByLabelText("Name for minutes.pdf");
    expect(name).toHaveValue("minutes");
    await user.clear(name);
    await user.type(name, "Committee minutes");
    expect(screen.getByLabelText("Name for cat.png")).toHaveValue("cat");

    await user.click(screen.getByRole("button", { name: "Upload 2 files" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith("/c/3/i/4/files"));
    expect(landShare).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "upload",
        uploads: [
          { file: PDF, name: "Committee minutes" },
          { file: PNG, name: "cat" },
        ],
      })
    );
  });

  it("will not upload a file with no name", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    const user = userEvent.setup();
    renderWizard(vi.fn(), { ...share, texts: [], files: [PDF] });

    await user.click(await screen.findByText("File"));
    await user.clear(await screen.findByLabelText("Name for minutes.pdf"));

    expect(screen.getByRole("button", { name: "Upload file" })).toBeDisabled();
  });

  it("says which files a document leaves out", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    const user = userEvent.setup();
    renderWizard(vi.fn(), { ...share, files: [PNG, PDF] });

    await user.click(await screen.findByText("Document"));

    expect(
      await screen.findByText("1 file isn't a picture, so it stays out. Choose File to upload it.")
    ).toBeInTheDocument();
  });

  it("makes a task in the project picked, and goes to it", async () => {
    const user = userEvent.setup();
    const onDone = renderWizard();

    await user.click(await screen.findByText("Task"));
    await user.click(await screen.findByText("Anvil Club"));
    await user.click(await screen.findByText("Spring Play"));
    await user.click(await screen.findByText("Props"));

    expect(await screen.findByText("Anvil Club > Spring Play > Props")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("A great article");
    expect(screen.getByLabelText("Note")).toHaveValue("https://example.com/article");

    await user.click(screen.getByRole("button", { name: "Create task" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith("/c/3/i/4/projects/6/tasks/77"));
    expect(landShare).toHaveBeenCalledWith({
      kind: "task",
      destination: {
        communityId: 3,
        communityName: "Anvil Club",
        initiativeId: 4,
        initiativeName: "Spring Play",
        projectId: 6,
        projectName: "Props",
      },
      title: "A great article",
      note: "https://example.com/article",
      images: [],
    });
  });

  it("offers only initiatives where posts can be made", async () => {
    const user = userEvent.setup();
    renderWizard();

    await user.click(await screen.findByText("Post"));
    await user.click(await screen.findByText("Bellwether"));

    expect(creatableFor).toHaveBeenCalledWith("post", 8);
  });

  it("walks past a choice there is only one of", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    const user = userEvent.setup();
    renderWizard();

    await user.click(await screen.findByText("Document"));

    expect(await screen.findByText("Anvil Club > Spring Play")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create document" })).toBeInTheDocument();
  });

  const BELLWETHER_POST = {
    post: {
      communityId: 8,
      communityName: "Bellwether",
      initiativeId: 5,
      initiativeName: "Summer Play",
    },
  };

  it("offers the place last shared to on this server", async () => {
    stored.set(
      "initiative-last-share-destination",
      JSON.stringify({ "http://localhost": BELLWETHER_POST })
    );
    const user = userEvent.setup();
    renderWizard();

    await user.click(await screen.findByText("Post"));
    await user.click(await screen.findByText("Last used"));

    expect(await screen.findByText("Bellwether > Summer Play")).toBeInTheDocument();
  });

  it("does not offer a place last shared to on another server", async () => {
    stored.set(
      "initiative-last-share-destination",
      JSON.stringify({ "https://elsewhere.example/api/v1": BELLWETHER_POST })
    );
    const user = userEvent.setup();
    renderWizard();

    await user.click(await screen.findByText("Post"));

    expect(await screen.findByText("Anvil Club")).toBeInTheDocument();
    expect(screen.queryByText("Last used")).not.toBeInTheDocument();
  });

  it("remembers where it shared, under this server", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    landShare.mockResolvedValueOnce("/c/3/i/4/posts/9");
    const user = userEvent.setup();
    const onDone = renderWizard();

    await user.click(await screen.findByText("Post"));
    await user.click(await screen.findByRole("button", { name: "Post" }));
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());

    const saved = JSON.parse(stored.get("initiative-last-share-destination") ?? "{}");
    expect(saved).toEqual({
      "http://localhost": {
        post: {
          communityId: 3,
          communityName: "Anvil Club",
          initiativeId: 4,
          initiativeName: "Spring Play",
        },
      },
    });
  });

  it("says why a title with a sigil cannot be used", async () => {
    shownCommunities = [communities[0]];
    initiativesResult = oneInitiative;
    const user = userEvent.setup();
    renderWizard();

    await user.click(await screen.findByText("Post"));
    const title = await screen.findByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Ask @moss");

    expect(screen.getByText("Names and titles can’t contain # or @.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post" })).toBeDisabled();
  });

  it("puts the share down on Cancel", async () => {
    const user = userEvent.setup();
    const onDone = renderWizard();

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(onDone).toHaveBeenCalledWith();
    expect(landShare).not.toHaveBeenCalled();
  });
});

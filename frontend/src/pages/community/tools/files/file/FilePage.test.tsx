import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildFileSummary } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { getReadFileQueryKey } from "@/api/generated/files/files";
import { queryClient as appQueryClient } from "@/lib/queryClient";
import { CollaborationError } from "@/lib/yjs/CollaborationProvider";

const collaborating = { value: false };
const network = { online: true };
const collaboration: { onError?: (error: Error) => void } = {};
const toasts = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn() }));

vi.mock("@/lib/mascotToast", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    info: vi.fn(),
    error: toasts.error,
    warning: toasts.warning,
    dismiss: vi.fn(),
  }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: network.online }),
}));

vi.mock("@/hooks/useCollaboration", () => ({
  useCollaboration: (options: { onError?: (error: Error) => void }) => {
    collaboration.onError = options.onError;
    return {
      providerFactory: null,
      connectionStatus: collaborating.value ? "connected" : "disconnected",
      isSynced: collaborating.value,
      collaborators: [],
      collaboratorsReady: collaborating.value,
      isCollaborating: collaborating.value,
      isReady: true,
      connect: vi.fn(),
      resume: vi.fn(),
      disconnect: vi.fn(),
    };
  },
}));

vi.mock("@/components/tools/files/WhiteboardFileEditor", () => ({
  WhiteboardFileEditor: () => <div>whiteboard canvas</div>,
}));

const editedBody = { root: { children: [{ type: "edited" }] } };

// Stands in for Lexical, exposing the one thing these tests drive: a body edit,
// reported back the way the real editor reports one.
vi.mock("@/components/editor/editor", () => ({
  Editor: ({ onSerializedChange }: { onSerializedChange: (state: unknown) => void }) => (
    <button type="button" onClick={() => onSerializedChange(editedBody)}>
      edit the body
    </button>
  ),
}));

const seed = {
  ...buildFileSummary({ id: 7, name: "Original", initiative_id: 1 }),
  collection_ids: [],
};

const patches: Record<string, unknown>[] = [];
/** What the server holds — a PATCH keeps what it was given, as the real one does. */
let stored: Record<string, unknown> = { ...seed };

beforeEach(() => {
  patches.length = 0;
  stored = { ...seed };
  collaborating.value = false;
  network.online = true;
  toasts.warning.mockClear();
  toasts.error.mockClear();
  server.use(
    communityHttp.get("/files/:fileId", () => HttpResponse.json(stored)),
    communityHttp.patch("/files/:fileId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push(body);
      stored = { ...stored, ...body };
      return HttpResponse.json(stored);
    }),
    communityHttp.put("/personal-items/view/:kind/:id", () => HttpResponse.json({})),
    communityHttp.get("/relationships/", () => HttpResponse.json([])),
    communityHttp.get("/properties/definitions", () => HttpResponse.json([]))
  );
});

const { FilePage } = await import("./FilePage");

// Restored here rather than at the end of each test so a failed assertion
// cannot leave fake timers behind for the next one.
afterEach(() => {
  vi.useRealTimers();
});

const renderDoc = (options: Parameters<typeof renderPage>[1] = {}) =>
  renderPage(FilePage, {
    initialRoute: "/g/$communityId/i/$initiativeId/files/$fileId",
    routeParams: { communityId: "1", initiativeId: "1", fileId: "7" },
    ...options,
  });

describe("renaming a file", () => {
  it("keeps the Save button beside the field while the name is being typed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.clear(input);
    await user.type(input, "Renamed");

    // Well past the autosave debounce, with the field still held.
    await vi.advanceTimersByTimeAsync(6000);

    expect(patches).toEqual([]);
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed" });
  });

  it.each([
    [false, 3000],
    [true, 11_000],
  ])("autosaves the name once the field is let go (collaborating: %s)", async (live, wait) => {
    collaborating.value = live;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.tab();

    await vi.advanceTimersByTimeAsync(wait);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed" });
  });

  it("keeps saving the body while the name field is held", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    await user.clear(input);
    await user.type(input, "Renamed");

    await vi.advanceTimersByTimeAsync(6000);

    // The body went; the half-typed name stayed behind with its Save button.
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toHaveProperty("content");
    expect(patches[0]).not.toHaveProperty("name");
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();
  });

  it("keeps the room's save running while the name field is held", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    await user.clear(input);
    await user.type(input, "Renamed");

    await vi.advanceTimersByTimeAsync(11_000);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).not.toHaveProperty("name");
  });

  it("does not PATCH on a loop while collaborating with nothing edited", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderDoc();
    await screen.findByDisplayValue("Original");

    await vi.advanceTimersByTimeAsync(45_000);

    expect(patches).toEqual([]);
  });

  // The room owns the body while it is live and refuses one sent by PATCH, so
  // a save sends only the name; the room renders the body.
  it.each(["the Save button", "Ctrl+S"])(
    "saves a rename with %s while collaborating",
    async (how) => {
      collaborating.value = true;
      const user = userEvent.setup();
      renderDoc();

      const input = await screen.findByDisplayValue("Original");
      await user.click(await screen.findByRole("button", { name: "edit the body" }));
      await user.clear(input);
      await user.type(input, "Renamed");
      if (how === "Ctrl+S") await user.keyboard("{Control>}s{/Control}");
      else await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toMatchObject({ name: "Renamed" });
      expect(patches[0]).not.toHaveProperty("content");
    }
  );

  it("saves a rename with Ctrl+S when not collaborating", async () => {
    const user = userEvent.setup();
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.keyboard("{Control>}s{/Control}");

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed", content: editedBody });
  });
});

describe("switching files", () => {
  it("shows the next file loading rather than the last one's body", async () => {
    let arrive = () => {};
    const arrived = new Promise<void>((resolve) => {
      arrive = resolve;
    });
    server.use(
      communityHttp.get("/files/:fileId", async ({ params }) => {
        if (params.fileId !== "8") return HttpResponse.json(stored);
        await arrived;
        return HttpResponse.json({
          ...buildFileSummary({ id: 8, name: "Second", initiative_id: 1 }),
          collection_ids: [],
        });
      })
    );
    // The app's own client keeps the last answer while the next one loads.
    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        ...queryClient.getDefaultOptions().queries,
        placeholderData: appQueryClient.getDefaultOptions().queries?.placeholderData,
      },
    });
    const { router } = renderDoc({ queryClient });
    await screen.findByRole("button", { name: "edit the body" });

    await router.navigate({ href: "/g/1/i/1/files/8" });

    // The page stays mounted across the switch: an editor still open on the
    // last file would report its body as the next one's edit.
    expect(await screen.findByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "edit the body" })).not.toBeInTheDocument();

    arrive();
    expect(await screen.findByDisplayValue("Second")).toBeInTheDocument();
    expect(patches).toEqual([]);
  });
});

describe("opening a whiteboard", () => {
  it("draws the canvas from the read the route made on the way in", async () => {
    // The route's loader fetches the file before the page mounts. Still fresh,
    // it is not fetched again on mount, and the canvas must not wait for a
    // fetch that never comes.
    const whiteboard = {
      ...seed,
      file_type: "excalidraw",
      content: { elements: [], appState: {}, files: {} },
    };
    stored = whiteboard;
    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: { ...queryClient.getDefaultOptions().queries, staleTime: 30_000, gcTime: 60_000 },
    });
    queryClient.setQueryData(getReadFileQueryKey(1, 7), whiteboard);

    renderDoc({ queryClient });

    expect(await screen.findByText("whiteboard canvas")).toBeInTheDocument();
  });
});

describe("losing the connection to a room", () => {
  it("tells an offline reader their edits will sync, and leaves a lost room to that", async () => {
    network.online = false;
    renderDoc();
    await screen.findByRole("button", { name: "edit the body" });

    expect(toasts.warning).toHaveBeenCalledWith(
      "You're offline — edits will sync when you reconnect.",
      expect.objectContaining({ id: "editor-offline" })
    );

    act(() => collaboration.onError?.(new CollaborationError("Connection lost.", true)));

    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("says so when the room is lost while the device is online", async () => {
    renderDoc();
    await screen.findByRole("button", { name: "edit the body" });

    act(() => collaboration.onError?.(new CollaborationError("Connection lost.", true)));

    expect(toasts.error).toHaveBeenCalledTimes(1);
  });
});

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { FileType } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { WhiteboardScene } from "@/components/files/WhiteboardFileEditor";
import { ToolExportCard } from "@/components/tools/settings/ToolExportCard";
import { ToolSettingsProvider } from "@/components/tools/settings/ToolSettingsContext";

import { useFileExportOptions } from "./useFileExportOptions";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@excalidraw/excalidraw", () => ({
  exportToBlob: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
  exportToSvg: vi.fn(async () => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    return svg;
  }),
}));

import { exportToBlob } from "@excalidraw/excalidraw";

import { ownerCan } from "@/__tests__/factories";
import { downloadBlob } from "@/lib/csv";

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

/** A file's export card, as its settings page mounts it. */
function FileExportCard({
  fileId,
  fileType,
  title,
  whiteboardScene,
}: {
  fileId: number;
  fileType: FileType;
  title: string;
  whiteboardScene?: WhiteboardScene;
}) {
  const exportOptions = useFileExportOptions(fileType, title, whiteboardScene);
  return (
    <ToolSettingsProvider
      value={{
        tool: Tool.file,
        entity: {
          id: fileId,
          name: title,
          initiative_id: 1,
          can: ownerCan(),
          tags: [],
          grants: [],
          comments_enabled: true,
          archived_at: null,
        },
        setGrants: noopMutation(),
        remove: noopMutation(),
        exportOptions,
      }}
    >
      <ToolExportCard />
    </ToolSettingsProvider>
  );
}

describe("a file's export card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("offers spreadsheet formats and sends the engine request", async () => {
    let sent: { format: string | null; ids: string | null } | null = null;
    server.use(
      communityHttp.get("/exports/file", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          ids: url.searchParams.get("ids"),
        };
        return new HttpResponse("a,b", {
          status: 200,
          headers: { "Content-Type": "text/csv" },
        });
      })
    );
    renderWithProviders(<FileExportCard fileId={9} fileType="sheet" title="Budget" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("button", { name: /csv/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual({ format: "csv", ids: "9" });
    expect(String(vi.mocked(downloadBlob).mock.calls[0][1])).toMatch(/^budget-.*\.csv$/);
  });

  it("names the download from the server's Content-Disposition", async () => {
    server.use(
      communityHttp.get(
        "/exports/file",
        () =>
          new HttpResponse("{}", {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Content-Disposition": 'attachment; filename="notes-2026-07-13.json"',
            },
          })
      )
    );
    renderWithProviders(<FileExportCard fileId={5} fileType="lexical" title="Notes" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("button", { name: /json/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    // The server name wins over the client's {stem}.{format} fallback.
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("notes-2026-07-13.json");
  });

  it("renders whiteboard PNG client-side without touching the engine", async () => {
    const engineHit = vi.fn();
    server.use(
      communityHttp.get("/exports/file", () => {
        engineHit();
        return HttpResponse.json({});
      })
    );
    renderWithProviders(
      <FileExportCard
        fileId={4}
        fileType="excalidraw"
        title="Board"
        whiteboardScene={{ elements: [], appState: {}, files: {} }}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("button", { name: /png/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(exportToBlob).toHaveBeenCalledTimes(1);
    expect(engineHit).not.toHaveBeenCalled();
    expect(String(vi.mocked(downloadBlob).mock.calls[0][1])).toMatch(/^board-.*\.png$/);
  });

  it("offers a single-format type its one format (file passthrough)", async () => {
    server.use(
      communityHttp.get(
        "/exports/file",
        () =>
          new HttpResponse("bytes", {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          })
      )
    );
    renderWithProviders(<FileExportCard fileId={2} fileType="pdf" title="Upload" />);

    // One format: nothing to choose, so the wizard opens on it.
    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(await screen.findByText("Original file")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
  });
});

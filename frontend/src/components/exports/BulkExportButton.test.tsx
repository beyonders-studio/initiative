import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildFileSummary, ownerCan, writerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { BulkExportButton } from "./BulkExportButton";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

describe("BulkExportButton", () => {
  it("exports a selection its viewer owns every item of", () => {
    renderWithProviders(
      <BulkExportButton
        tool={Tool.queue}
        items={[
          { id: 1, can: ownerCan() },
          { id: 2, can: ownerCan() },
        ]}
      />
    );

    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });

  it("says why when one of the selection is only theirs to edit", () => {
    renderWithProviders(
      <BulkExportButton
        tool={Tool.queue}
        items={[
          { id: 1, can: ownerCan() },
          { id: 2, can: writerCan() },
        ]}
      />
    );

    const button = screen.getByRole("button", {
      name: "Only whoever can delete all of these can export them.",
    });
    expect(button).toBeDisabled();
  });
});

describe("BulkExportButton for files", () => {
  it("sends the selected ids and downloads the zip", async () => {
    let sent: string[] = [];
    server.use(
      communityHttp.get("/exports/file", ({ request }) => {
        sent = new URL(request.url).searchParams.getAll("ids");
        return new HttpResponse("PK-zip-bytes", {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="file-2026-07-14.zip"',
          },
        });
      })
    );
    const docs = [
      buildFileSummary({ id: 11, file_type: "lexical" }),
      buildFileSummary({ id: 12, file_type: "lexical" }),
    ];
    renderWithProviders(<BulkExportButton tool={Tool.file} items={docs} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("button", { name: /json/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual(["11", "12"]);
    // Server names the bundle; the client fallback stem never fires.
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("file-2026-07-14.zip");
  });

  it("offers only the formats every selected type shares", async () => {
    const docs = [
      buildFileSummary({ id: 1, file_type: "lexical" }),
      buildFileSummary({ id: 2, file_type: "sheet" }),
    ];
    renderWithProviders(<BulkExportButton tool={Tool.file} items={docs} />);

    // json is the only shared format, so the wizard asks nothing and names it.
    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(await screen.findByRole("button", { name: /start export/i })).toBeInTheDocument();
    expect(screen.getByText(/json/i)).toBeInTheDocument();
    expect(screen.queryByText(/pdf|csv/i)).not.toBeInTheDocument();
  });

  it("says why when the selected types share no format", () => {
    const docs = [
      buildFileSummary({ id: 1, file_type: "lexical" }),
      buildFileSummary({ id: 2, file_type: "pdf" }),
    ];
    renderWithProviders(<BulkExportButton tool={Tool.file} items={docs} />);

    expect(
      screen.getByRole("button", { name: "These share no format they can all be exported to." })
    ).toBeDisabled();
  });
});

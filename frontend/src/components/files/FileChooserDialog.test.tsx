import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildFileSummary } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { FileChooserDialog } from "./FileChooserDialog";

describe("FileChooserDialog", () => {
  it("offers every kind of file, and leaves out what the place already holds", async () => {
    let asked = null as URLSearchParams | null;
    const items = [
      buildFileSummary({ id: 1, name: "Minutes", file_type: "lexical" }),
      buildFileSummary({
        id: 2,
        name: "proof.pdf",
        file_type: "pdf",
        original_filename: "proof.pdf",
        file_content_type: "application/pdf",
      }),
      buildFileSummary({ id: 3, name: "Budget", file_type: "sheet" }),
      buildFileSummary({ id: 4, name: "Already there", file_type: "excalidraw" }),
    ];
    server.use(
      communityHttp.get("/files/", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({
          items,
          total_count: items.length,
          page: 1,
          page_size: 0,
          has_next: false,
        });
      })
    );

    renderWithProviders(
      <FileChooserDialog
        initiativeId={1}
        exclude={new Set([4])}
        open
        onOpenChange={() => {}}
        onPick={() => {}}
        pending={false}
        text={{ title: "Add a file", description: "Which file?", none: "No files to add" }}
      />
    );

    expect(await screen.findByText("proof.pdf")).toBeInTheDocument();
    expect(screen.getByText("Minutes")).toBeInTheDocument();
    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.queryByText("Already there")).not.toBeInTheDocument();
    expect(asked?.get("file_type")).toBeNull();
  });
});

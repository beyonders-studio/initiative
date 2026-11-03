import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildFileSummary } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { FileRead } from "@/api/generated/initiativeAPI.schemas";

import { isWideFile, WikiFileBody } from "./WikiFileBody";

vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useNavigate: () => vi.fn(),
}));

// Each kind's own renderer, stood in for by a line saying which it was and
// whether it was told to stay read-only.
vi.mock("@/components/ui/editor/editor", () => ({
  Editor: ({ readOnly }: { readOnly?: boolean }) => <p>prose {readOnly ? "read-only" : ""}</p>,
}));
vi.mock("@/components/files/UploadedFileViewer", () => ({
  UploadedFileViewer: ({
    originalFilename,
    canEdit,
  }: {
    originalFilename?: string;
    canEdit?: boolean;
  }) => (
    <p>
      file {originalFilename} {canEdit ? "editable" : "read-only"}
    </p>
  ),
}));
vi.mock("@/components/files/WhiteboardFileEditor", () => ({
  WhiteboardFileEditor: ({ readOnly }: { readOnly?: boolean }) => (
    <p>canvas {readOnly ? "read-only" : ""}</p>
  ),
}));
vi.mock("@/components/files/SpreadsheetFileEditor", () => ({
  SpreadsheetFileEditor: ({ readOnly }: { readOnly?: boolean }) => (
    <p>grid {readOnly ? "read-only" : ""}</p>
  ),
}));
vi.mock("@/components/files/SmartLinkFileViewer", () => ({
  SmartLinkFileViewer: () => <p>link</p>,
}));

const fileOf = (overrides: Partial<FileRead>) =>
  ({ ...buildFileSummary(), content: {}, ...overrides }) as FileRead;

describe("WikiFileBody", () => {
  it.each([
    [
      fileOf({
        file_type: "pdf",
        file_url: "/uploads/1/abc.pdf",
        original_filename: "proof.pdf",
      }),
      "file proof.pdf read-only",
    ],
    [fileOf({ file_type: "excalidraw" }), "canvas read-only"],
    [fileOf({ file_type: "sheet" }), "grid read-only"],
    [fileOf({ file_type: "url" }), "link"],
    [fileOf({ file_type: "lexical" }), "prose read-only"],
  ])("draws a file the way its own kind is drawn", async (file, expected) => {
    renderWithProviders(<WikiFileBody file={file} />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("gives everything but prose the wide column", () => {
    expect(isWideFile(fileOf({ file_type: "lexical" }))).toBe(false);
    expect(isWideFile(fileOf({ file_type: "pdf" }))).toBe(true);
    expect(isWideFile(undefined)).toBe(false);
  });
});

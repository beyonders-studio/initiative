import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { FileType, type FileVersionRead } from "@/api/generated/initiativeAPI.schemas";

// Avoid pulling in the real react-pdf (pdf.js worker) during tests.
vi.mock("react-pdf", () => ({
  Document: () => null,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {}, version: "test" },
}));

// Fixed, predictable download URLs so we can assert which version is rendered.
vi.mock("@/lib/uploadUrl", () => ({
  resolveFileDownloadUrl: (id: number, inline?: boolean) => `/dl/${id}${inline ? "?inline=1" : ""}`,
  resolveFileVersionDownloadUrl: (id: number, vid: number, inline?: boolean) =>
    `/dl/${id}/v/${vid}${inline ? "?inline=1" : ""}`,
}));

const uploadMutate = vi.fn();
const deleteMutate = vi.fn();
const putThumbnail = vi.fn();
const convertMutate = vi.fn();
const frame = new Blob(["frame"], { type: "image/webp" });

const frameSignals: AbortSignal[] = [];

vi.mock("@/lib/videoFrame", () => ({
  drawVideoFrame: (_url: string, signal: AbortSignal) => {
    frameSignals.push(signal);
    return Promise.resolve(frame);
  },
}));
let mockVersions: FileVersionRead[] = [];

vi.mock("@/hooks/useFiles", () => ({
  useFileVersions: () => ({ data: mockVersions }),
  useUploadFileVersion: () => ({ mutate: uploadMutate, isPending: false }),
  useDeleteFileVersion: () => ({ mutate: deleteMutate, isPending: false }),
  usePutVideoThumbnail: () => ({ mutate: putThumbnail }),
  useConvertFile: () => ({ mutate: convertMutate, isPending: false }),
}));

// Import after mocks are registered.
import { UploadedFileViewer } from "./UploadedFileViewer";

const buildVersion = (overrides: Partial<FileVersionRead>): FileVersionRead => ({
  id: 1,
  version_number: 1,
  file_content_type: "application/pdf",
  file_size: 100,
  original_filename: "doc.pdf",
  created_by: 1,
  created_at: "2026-05-28T00:00:00Z",
  is_current: false,
  ...overrides,
});

const renderViewer = (props: Partial<Parameters<typeof UploadedFileViewer>[0]> = {}) =>
  renderWithProviders(
    <UploadedFileViewer
      fileId={5}
      communityId={7}
      fileUrl="/uploads/doc.pdf"
      contentType="application/pdf"
      originalFilename="doc.pdf"
      fileType={FileType.pdf}
      fileSize={100}
      {...props}
    />
  );

describe("UploadedFileViewer version controls", () => {
  beforeEach(() => {
    uploadMutate.mockClear();
    deleteMutate.mockClear();
    mockVersions = [
      buildVersion({ id: 2, version_number: 2, is_current: true }),
      buildVersion({ id: 1, version_number: 1, is_current: false }),
    ];
  });

  it("hides upload + delete for a read-only viewer", async () => {
    renderViewer({ canEdit: false, canDeleteVersions: false });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.queryByText(/upload new version/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument();
  });

  it("shows the upload action for a writer", async () => {
    renderViewer({ canEdit: true, canDeleteVersions: false });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.getByText(/upload new version/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument();
  });

  it("lets the owner delete a non-last version", async () => {
    renderViewer({ canEdit: true, canDeleteVersions: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    const deleteButtons = screen.getAllByRole("button", { name: /delete version/i });
    expect(deleteButtons.length).toBe(2);
    expect(deleteButtons[0]).toBeEnabled();
  });

  it("disables delete when only one version exists", async () => {
    mockVersions = [buildVersion({ id: 2, version_number: 1, is_current: true })];
    renderViewer({ canEdit: true, canDeleteVersions: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.getByRole("button", { name: /delete version/i })).toBeDisabled();
  });

  it("switches the viewer to an older version and shows the notice", async () => {
    renderViewer({ canEdit: true, canDeleteVersions: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    await userEvent.click(screen.getByRole("button", { name: /version 1/i }));
    await waitFor(() => expect(screen.getByText(/viewing an older version/i)).toBeInTheDocument());
  });
});

describe("UploadedFileViewer media", () => {
  beforeEach(() => putThumbnail.mockClear());

  const playing = (
    contentType: string,
    name: string,
    props: Partial<Parameters<typeof UploadedFileViewer>[0]> = {}
  ) => {
    const fileType = contentType.startsWith("video/") ? FileType.mp4 : FileType.mp3;
    mockVersions = [
      buildVersion({
        id: 2,
        is_current: true,
        file_content_type: contentType,
        original_filename: name,
      }),
    ];
    return renderViewer({
      contentType,
      fileType,
      originalFilename: name,
      fileUrl: `/uploads/${name}`,
      ...props,
    });
  };

  it("plays a video in the browser's player", () => {
    const { container } = playing("video/mp4", "clip.mp4");
    const video = container.querySelector("video");
    expect(video).toHaveAttribute("src", "/dl/5/v/2?inline=1");
    expect(video).toHaveAttribute("controls");
  });

  it("plays a recording in the browser's player", () => {
    const { container } = playing("audio/mpeg", "take.mp3");
    expect(container.querySelector("audio")).toHaveAttribute("src", "/dl/5/v/2?inline=1");
    expect(screen.getByRole("heading", { name: "take.mp3" })).toBeInTheDocument();
  });

  it("gives a video without a thumbnail a frame of itself, for an editor", async () => {
    playing("video/mp4", "clip.mp4", { canEdit: true });

    await waitFor(() =>
      expect(putThumbnail).toHaveBeenCalledWith({ fileId: 5, versionId: 2, frame })
    );
  });

  it("stops drawing a frame when the viewer goes", () => {
    const { unmount } = playing("video/mp4", "clip.mp4", { canEdit: true });

    unmount();

    expect(frameSignals.at(-1)?.aborted).toBe(true);
  });

  it("names an older recording by its own name", async () => {
    mockVersions = [
      buildVersion({
        id: 2,
        version_number: 2,
        is_current: true,
        file_content_type: "audio/mpeg",
        original_filename: "take-2.mp3",
      }),
      buildVersion({ id: 1, file_content_type: "audio/mpeg", original_filename: "take-1.mp3" }),
    ];
    renderViewer({
      contentType: "audio/mpeg",
      fileType: FileType.mp3,
      originalFilename: "take-2.mp3",
      fileUrl: "/uploads/take-2.mp3",
    });

    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    await userEvent.click(screen.getByRole("button", { name: /version 1/i }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "take-1.mp3" })).toBeInTheDocument()
    );
  });

  it("leaves a video's thumbnail to an editor, and one it already has alone", async () => {
    playing("video/mp4", "clip.mp4", { canEdit: false });
    playing("video/mp4", "clip.mp4", {
      canEdit: true,
      thumbnailUrl: "/uploads/7/thumbnail-a.webp",
    });

    await new Promise((settle) => setTimeout(settle, 0));
    expect(putThumbnail).not.toHaveBeenCalled();
  });
});

describe("UploadedFileViewer cards", () => {
  it("offers a design file for download rather than drawing it as a picture", () => {
    mockVersions = [];
    const { container } = renderViewer({
      contentType: "image/vnd.adobe.photoshop",
      fileType: FileType.psd,
      originalFilename: "poster.psd",
      fileUrl: "/uploads/poster.psd",
    });

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("heading", { name: "poster.psd" })).toBeInTheDocument();
    expect(screen.getByText("PSD")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /download/i }).length).toBeGreaterThan(0);
  });
});

describe("UploadedFileViewer convert to edit", () => {
  beforeEach(() => {
    mockVersions = [];
    convertMutate.mockReset();
  });

  const csv = {
    contentType: "text/csv",
    originalFilename: "budget.csv",
    fileType: FileType.csv,
    convertsTo: FileType.sheet,
  };

  it("converts a spreadsheet once the editor says so, after saying what comes over", async () => {
    renderViewer({ ...csv, canEdit: true });

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText(/its rows and columns as one sheet/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Convert" }));

    expect(convertMutate).toHaveBeenCalledWith(5);
  });

  it("offers nothing to somebody who can only read the file", () => {
    renderViewer({ ...csv, canEdit: false });

    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });
});

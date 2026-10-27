import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { acceptsNonImages, ImagePicker } from "./image-picker";

const canCapturePhoto = vi.fn(() => false);
const capturePhoto = vi.fn();

vi.mock("@/lib/nativeCamera", async () => {
  const actual = await vi.importActual<typeof import("@/lib/nativeCamera")>("@/lib/nativeCamera");
  return {
    ...actual,
    canCapturePhoto: () => canCapturePhoto(),
    capturePhoto: (source: "camera" | "library") => capturePhoto(source),
  };
});

const toastError = vi.fn();
vi.mock("@/lib/mascotToast", () => ({ toast: { error: (m: string) => toastError(m) } }));

const photo = () => new File(["binary"], "photo-1.jpg", { type: "image/jpeg" });

beforeEach(() => {
  canCapturePhoto.mockReturnValue(false);
  capturePhoto.mockReset();
  toastError.mockReset();
});

describe("acceptsNonImages", () => {
  it("is false for an image-only list", () => {
    expect(acceptsNonImages("image/*")).toBe(false);
    expect(acceptsNonImages("image/png,image/jpeg,.webp")).toBe(false);
  });

  it("is true once anything else is allowed", () => {
    expect(acceptsNonImages(".png,.pdf")).toBe(true);
    expect(acceptsNonImages("image/*,application/pdf")).toBe(true);
    expect(acceptsNonImages("")).toBe(true);
  });
});

describe("in a browser", () => {
  it("is the file field it replaces", async () => {
    const onSelect = vi.fn();
    const { container } = render(<ImagePicker onSelect={onSelect} id="pic" />);

    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    expect(input).toBeVisible();
    expect(input.accept).toBe("image/*");
    expect(input.id).toBe("pic");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    fireEvent.change(input, { target: { files: [photo()] } });
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(expect.any(File)));
  });

  it("opens the file dialog from a button when asked for one", async () => {
    const onSelect = vi.fn();
    const { container } = render(
      <ImagePicker variant="button" onSelect={onSelect}>
        Upload
      </ImagePicker>
    );

    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    const clicked = vi.spyOn(input, "click");
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    expect(clicked).toHaveBeenCalled();
  });

  it("never reaches for the camera", async () => {
    const { container } = render(<ImagePicker onSelect={vi.fn()} />);

    fireEvent.change(container.querySelector("input[type=file]") as HTMLInputElement, {
      target: { files: [photo()] },
    });

    expect(capturePhoto).not.toHaveBeenCalled();
  });
});

describe("on the native app", () => {
  beforeEach(() => canCapturePhoto.mockReturnValue(true));

  it("offers the camera first, and hides the file field", async () => {
    const { container } = render(<ImagePicker onSelect={vi.fn()} />);

    // jsdom has no stylesheet, so the class Tailwind hides it with is the
    // assertion available here.
    expect(container.querySelector("input[type=file]")).toHaveClass("hidden");
    await userEvent.click(screen.getByRole("button"));

    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["Take a photo", "Choose from library"]);
  });

  it("hands the captured photo to the caller", async () => {
    const onSelect = vi.fn();
    capturePhoto.mockResolvedValue(photo());
    render(<ImagePicker onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Take a photo" }));

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(expect.any(File)));
    expect(capturePhoto).toHaveBeenCalledWith("camera");
  });

  it("picks from the library when that is what was chosen", async () => {
    capturePhoto.mockResolvedValue(photo());
    render(<ImagePicker onSelect={vi.fn()} />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Choose from library" }));

    await waitFor(() => expect(capturePhoto).toHaveBeenCalledWith("library"));
  });

  it("says nothing when the capture was cancelled", async () => {
    const onSelect = vi.fn();
    capturePhoto.mockResolvedValue(null);
    render(<ImagePicker onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Take a photo" }));

    await waitFor(() => expect(capturePhoto).toHaveBeenCalled());
    expect(onSelect).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("explains a refused permission", async () => {
    const { PhotoCaptureError } = await import("@/lib/nativeCamera");
    capturePhoto.mockRejectedValue(new PhotoCaptureError("permission"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ImagePicker onSelect={vi.fn()} />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Take a photo" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "Initiative needs permission to use your camera and photos. Allow it in your device settings, then try again."
      )
    );
  });

  it("also offers a plain file when the accept list takes more than images", async () => {
    render(<ImagePicker onSelect={vi.fn()} accept=".png,.pdf" />);

    await userEvent.click(screen.getByRole("button"));

    expect(await screen.findByRole("menuitem", { name: "Choose a file" })).toBeInTheDocument();
  });
});

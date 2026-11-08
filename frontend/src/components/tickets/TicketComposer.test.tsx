/**
 * The box tickets are written in: the camera that takes a picture of the
 * page behind it, and the editor a picture opens in.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const drawn = () => ({
  svg: document.createElementNS("http://www.w3.org/2000/svg", "svg"),
  width: 800,
  height: 600,
});
const pictureOf = vi.hoisted(() => vi.fn());

vi.mock("@/lib/pagePicture", async () => {
  const actual = await vi.importActual<typeof import("@/lib/pagePicture")>("@/lib/pagePicture");
  return {
    ...actual,
    loadedPeople: () => new Map(),
    pictureThePage: async () => drawn(),
    pictureOf,
  };
});

// jsdom has no canvas to paint on: the picture made is a stand-in file.
vi.mock("@/components/tickets/PictureEditor", async () => {
  const actual = await vi.importActual<typeof import("./PictureEditor")>("./PictureEditor");
  return {
    ...actual,
    makePicture: async (_session: unknown, _size: unknown, name: string) =>
      new File(["png"], `${name}.png`, { type: "image/png" }),
  };
});

import { TicketComposer } from "./TicketComposer";

const POLICY = { max_files: 3, max_bytes: 10_000, types: ["image/png", "image/jpeg"] };

const box = (props: Partial<React.ComponentProps<typeof TicketComposer>> = {}) =>
  renderWithProviders(
    <TicketComposer
      aria-label="What's going on?"
      value=""
      onChange={() => {}}
      policy={POLICY}
      files={[]}
      onFilesChange={() => {}}
      {...props}
    />,
    { auth: { user: buildUser() } }
  );

describe("TicketComposer", () => {
  it("takes a picture of the page, with the people on it hidden to start with", async () => {
    box({ pagePicture: { hidePeople: true } });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Picture this page" }));

    expect(await screen.findByRole("dialog", { name: "Picture of this page" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Hide people" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Attach picture" })).toBeInTheDocument();
  });

  it("keeps Enter in the editor from sending what the box is in", async () => {
    const send = vi.fn();
    renderWithProviders(
      <div onKeyDown={send}>
        <TicketComposer
          aria-label="What's going on?"
          value=""
          onChange={() => {}}
          policy={POLICY}
          files={[]}
          onFilesChange={() => {}}
          pagePicture={{ hidePeople: true }}
        />
      </div>,
      { auth: { user: buildUser() } }
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Picture this page" }));
    await screen.findByRole("dialog", { name: "Picture of this page" });

    screen.getByRole("application").focus();
    await user.keyboard("{Control>}{Enter}{/Control}");

    expect(send).not.toHaveBeenCalledWith(expect.objectContaining({ key: "Enter" }));
  });

  it("takes a picture of the thing as it opens, when asked, and attaches it", async () => {
    pictureOf.mockResolvedValue(drawn());
    const thing = document.createElement("article");
    document.body.append(thing);
    const onFilesChange = vi.fn();
    box({ pagePicture: { hidePeople: false, takenOf: thing }, onFilesChange });

    await waitFor(() => expect(onFilesChange).toHaveBeenCalledTimes(1));
    expect(pictureOf).toHaveBeenCalledWith(thing);
    expect(onFilesChange.mock.calls[0][0].map((file: File) => file.name)).toEqual([
      "Picture of this page.png",
    ]);
    // Attached as it is: the editor opens only when asked.
    expect(screen.queryByRole("dialog")).toBeNull();
    thing.remove();
  });

  it("leaves the people showing where the box says so", async () => {
    box({ pagePicture: { hidePeople: false } });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Picture this page" }));

    expect(await screen.findByRole("switch", { name: "Hide people" })).not.toBeChecked();
  });

  it("offers no picture of the page where the box is not over one", () => {
    box();
    expect(screen.queryByRole("button", { name: "Picture this page" })).toBeNull();
    expect(screen.getByRole("button", { name: "Attach files" })).toBeInTheDocument();
  });

  it("opens an attached picture in the editor, which keeps nothing the file carried", async () => {
    const shot = new File(["png"], "shot.png", { type: "image/png" });
    box({ files: [shot] });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit shot.png" }));

    expect(await screen.findByRole("dialog", { name: "shot.png" })).toBeInTheDocument();
    expect(screen.getByText(/draws a fresh copy/)).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Hide people" })).toBeNull();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });
});

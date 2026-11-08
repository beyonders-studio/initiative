import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildFileSummary, buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ImageChooser } from "./ImageChooser";

describe("ImageChooser", () => {
  it("opens on the page's initiative and picks the picture's current version", async () => {
    let asked = null as URLSearchParams | null;
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: 1, name: "First" }),
          buildInitiative({ id: 2, name: "The page's" }),
          buildInitiative({ id: 3, name: "No files", files_enabled: false }),
        ])
      ),
      communityHttp.get("/files/", ({ request }) => {
        asked = new URL(request.url).searchParams;
        const items = [
          buildFileSummary({
            id: 7,
            name: "Dawn",
            file_type: "png",
            file_url: "/uploads/1/dawn-v2.png",
            thumbnail_url: "/uploads/1/thumbnail-dawn.webp",
          }),
        ];
        return HttpResponse.json({
          items,
          total_count: items.length,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        });
      })
    );
    const onPick = vi.fn();

    renderWithProviders(<ImageChooser initiativeId={2} onPick={onPick} />);

    await userEvent.click(await screen.findByRole("button", { name: "Dawn" }));
    expect(onPick).toHaveBeenCalledWith({ src: "/uploads/1/dawn-v2.png", name: "Dawn" });
    expect(asked?.get("initiative_id")).toBe("2");
    expect(asked?.get("kind")).toBe("image");
  });
});

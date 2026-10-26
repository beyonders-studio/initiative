/**
 * One card for any kind of thing.
 *
 * What is worth asserting is that it draws *something* for every kind — a
 * picture, an emoji, a colour, or the kind's own mark — that a file picks
 * the mark matching what sort of file it is, and that the two things it
 * must not get wrong: offering a link it cannot build, and offering to unlink
 * something nobody may unlink by hand.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { type RelatedEnd, SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";

import { EntityCard } from "./EntityCard";

const end = (overrides: Partial<RelatedEnd> = {}): RelatedEnd => ({
  type: SearchEntityType.file,
  id: 4,
  title: "Onboarding checklist",
  initiative_id: 3,
  updated_at: null,
  tool: Tool.file,
  tool_id: 4,
  tool_title: null,
  image_urls: [],
  icon: null,
  color: null,
  file_type: "lexical",
  mime_type: null,
  original_filename: null,
  smart_link_url: null,
  is_open: null,
  ...overrides,
});

const renderCard = (props: Partial<React.ComponentProps<typeof EntityCard>> = {}) =>
  renderPage(() => <EntityCard end={end()} {...props} />, { initialRoute: "/c/1" });

describe("EntityCard", () => {
  it("links to the thing it names", async () => {
    renderCard();
    const link = await screen.findByRole("link", { name: /Onboarding checklist/ });
    expect(link.getAttribute("href")).toContain("/files/4");
  });

  it("still reaches a thing whose parent did not come back", async () => {
    // A task is addressed inside its project, and without that id there is no
    // direct address — but the thing has a page, so the resolver finds it.
    renderCard({ end: end({ type: SearchEntityType.task, id: 9, tool: null, tool_id: null }) });

    const link = await screen.findByRole("link", { name: /Onboarding checklist/ });
    expect(link.getAttribute("href")).toContain("/go/task/9");
  });

  it("draws a picture when the thing has one", async () => {
    const { container } = renderCard({ end: end({ image_urls: ["/uploads/3/cover.png"] }) });
    // LazyImage falls back to loading eagerly with no IntersectionObserver,
    // which is what jsdom gives it.
    await screen.findByText("Onboarding checklist");
    expect(container.querySelector("img")).toHaveAttribute("src", "/uploads/3/cover.png");
  });

  it("draws every picture a thing offers, not just the first", async () => {
    // A catalog nobody picked a cover for stands for itself with its newest
    // few, the way it does everywhere else in the app.
    const { container } = renderCard({
      end: end({
        type: SearchEntityType.catalog,
        tool: Tool.catalog,
        image_urls: ["/uploads/3/a.webp", "/uploads/3/b.webp", "/uploads/3/c.webp"],
      }),
    });
    await screen.findByText("Onboarding checklist");
    expect(container.querySelectorAll("img")).toHaveLength(3);
  });

  it("draws the one picture a thing chose on its own", async () => {
    const { container } = renderCard({
      end: end({
        type: SearchEntityType.catalog,
        tool: Tool.catalog,
        image_urls: ["/uploads/3/cover.webp"],
      }),
    });
    await screen.findByText("Onboarding checklist");
    expect(container.querySelectorAll("img")).toHaveLength(1);
  });

  it("says the same things in a row as it does in a tile", async () => {
    renderCard({ variant: "compact", end: end({ title: "Onboarding checklist" }) });
    expect(await screen.findByText("Onboarding checklist")).toBeInTheDocument();
    expect(screen.getByRole("link")).toBeInTheDocument();
  });

  it("draws a colour for a thing whose identity is one", async () => {
    const { container } = renderCard({
      end: end({ type: SearchEntityType.tag, id: 5, tool: null, tool_id: null, color: "#112233" }),
    });
    await screen.findByText("Onboarding checklist");
    expect(container.querySelector('[style*="rgb(17, 34, 51)"]')).toBeTruthy();
  });

  it("draws a project's own emoji", async () => {
    renderCard({
      end: end({
        type: SearchEntityType.project,
        id: 2,
        tool: Tool.project,
        tool_id: 2,
        icon: "🎲",
      }),
    });
    expect(await screen.findByText("🎲")).toBeInTheDocument();
  });

  it("names what kind of thing it is", async () => {
    renderCard({ end: end({ type: SearchEntityType.task, tool: Tool.project, tool_id: 1 }) });
    expect(await screen.findByText(/task/i)).toBeInTheDocument();
  });

  it("offers to unlink a link somebody made", async () => {
    renderCard({ onRemove: vi.fn(), end: end() });
    expect(await screen.findByRole("button", { name: /Onboarding checklist/ })).toBeInTheDocument();
  });

  it("offers no unlink when the reader may not", async () => {
    renderCard();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

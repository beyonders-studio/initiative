import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderableBanner } from "@/lib/banner";

import { PageBanner } from "./PageBanner";

/** The banner under test, with the rest of it answered as a caller's would be. */
const banner = (look: Parameters<typeof renderableBanner>[0] = {}) => renderableBanner(look);

/** The fill and the artwork live on a layer under the copy, so the fade can be
 *  applied to one without touching the other. */
const ground = (container: HTMLElement) =>
  container.firstElementChild?.firstElementChild as HTMLElement;

/** The copy's own box — the heading, and the line under it. */
const copy = (container: HTMLElement) =>
  container.querySelector("h1")?.parentElement as HTMLElement;

/** The column the copy and the badge corner share, which is what carries the
 *  banner's minimum height and sits in the grid row the ground is behind. */
const column = (container: HTMLElement) => copy(container).parentElement as HTMLElement;

/** jsdom drops `mask-image` from a style declaration entirely, so the gradient
 *  itself is not assertable here. Everything it is derived from is: the extra
 *  row, the margin that gives it back, and which layer carries the fade. */
const fadeRow = (container: HTMLElement) =>
  (container.firstElementChild as HTMLElement).style.gridTemplateRows;

describe("PageBanner", () => {
  it("shows the picture when there is one, and nothing to see through the copy", () => {
    render(
      <PageBanner
        banner={banner({ image_url: "/images/banner.webp" })}
        title="Communities"
        subtitle="Find one"
      />
    );

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image).toHaveAttribute("src", "/images/banner.webp");
    expect(screen.getByRole("heading", { name: "Communities" })).toBeInTheDocument();
    expect(screen.getByText("Find one")).toBeInTheDocument();
  });

  it("falls back to the colour when there is no picture", () => {
    const { container } = render(
      <PageBanner banner={banner({ color: "#2a9d8f" })} title="Ravenloft" />
    );

    expect(container.querySelector("img")).toBeNull();
    expect(ground(container)).toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("prefers the picture when a community has set both", () => {
    const { container } = render(
      <PageBanner
        banner={banner({ image_url: "/api/v1/communities/1/image/abc", color: "#2a9d8f" })}
        title="Ravenloft"
      />
    );

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/communities/1/image/abc"
    );
    // The colour is the alternative, not a backdrop, so it is not painted too.
    expect(ground(container)).not.toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("takes the readable side of the contrast when no text colour is given", () => {
    const { rerender } = render(<PageBanner banner={banner({ color: "#101010" })} title="Dark" />);
    expect(screen.getByRole("heading", { name: "Dark" })).toHaveStyle({ color: "#ffffff" });

    rerender(<PageBanner banner={banner({ color: "#f5f0e8" })} title="Light" />);
    expect(screen.getByRole("heading", { name: "Light" })).toHaveStyle({ color: "#000000" });
  });

  it("uses the text colour it is given, including over artwork", () => {
    render(
      <PageBanner
        banner={banner({ image_url: "/api/v1/communities/1/image/abc", text_color: "#000000" })}
        title="Ravenloft"
      />
    );

    expect(screen.getByRole("heading", { name: "Ravenloft" })).toHaveStyle({ color: "#000000" });
  });

  it("backs the copy with a shadow of the opposite tone", () => {
    // The stored text colour is one answer for a banner whose brightness
    // varies across it, so the words carry their own contrast behind them.
    const { rerender } = render(
      <PageBanner banner={banner({ color: "#101010" })} title="Ravenloft" />
    );
    expect(screen.getByRole("heading", { name: "Ravenloft" }).style.textShadow).toContain(
      "rgba(0,0,0"
    );

    rerender(<PageBanner banner={banner({ color: "#f5f0e8" })} title="Ravenloft" />);
    expect(screen.getByRole("heading", { name: "Ravenloft" }).style.textShadow).toContain(
      "rgba(255,255,255"
    );
  });

  it("keeps the halo only where it is asked for, over fixed artwork", () => {
    render(
      <PageBanner
        banner={banner({ image_url: "/images/banner.webp" })}
        haloOverImage
        title="Communities"
      />
    );

    expect(screen.getByRole("heading", { name: "Communities" }).className).toContain("text-shadow");
  });

  it("is a short band with only a colour, and a tall one with a picture", () => {
    const { container, rerender } = render(
      <PageBanner banner={banner({ color: "#2563eb" })} title="Ravenloft" />
    );
    expect(column(container).className).toContain("min-h-24");

    rerender(
      <PageBanner banner={banner({ image_url: "/images/banner.webp" })} title="Ravenloft" />
    );
    expect(column(container).className).toContain("min-h-[44vw]");
  });

  it("centres the copy unless it is asked to align it left", () => {
    const { container, rerender } = render(
      <PageBanner banner={banner({ color: "#2563eb" })} title="Ravenloft" />
    );
    expect(copy(container).className).toContain("text-center");

    rerender(
      <PageBanner banner={banner({ color: "#2563eb", text_align: "left" })} title="Ravenloft" />
    );
    expect(copy(container).className).toContain("text-left");
    expect(copy(container).className).toContain("items-start");
  });

  it("does not fade, extend, or take back any margin unless asked to", () => {
    const { container } = render(
      <PageBanner banner={banner({ color: "#2563eb" })} title="Ravenloft" />
    );

    const element = container.firstElementChild as HTMLElement;
    expect(element.style.marginBottom).toBe("");
    expect(fadeRow(container)).toBe("");
    expect(ground(container).style.gridRow).toBe("1");
  });

  it("fades into the page and takes back exactly what it added", () => {
    // Adding a row and removing the same margin is what puts the page's own
    // content over the banner's tail without moving anything else.
    const { container } = render(
      <PageBanner
        banner={banner({ color: "#2563eb", fade: "strong" })}
        title="Ravenloft"
        subtitle="A community"
      />
    );

    const element = container.firstElementChild as HTMLElement;
    expect(fadeRow(container)).toBe("auto 224px");
    expect(element.style.marginBottom).toBe("-224px");
    // The ground spans both rows — the fade band is as much banner as the
    // rest of it — while the copy sits in the first row alone and stays opaque.
    expect(ground(container).style.gridRow).toBe("1 / span 2");
    expect(column(container).style.gridRow).toBe("1");
  });

  it("fades over a shorter tail on the weaker setting", () => {
    const { container } = render(
      <PageBanner banner={banner({ color: "#2563eb", fade: "weak" })} title="Ravenloft" />
    );

    const element = container.firstElementChild as HTMLElement;
    expect(fadeRow(container)).toBe("auto 48px");
    expect(element.style.marginBottom).toBe("-48px");
  });

  it("puts the badges in the corner, out of the copy it is not part of", () => {
    const { container, rerender } = render(
      <PageBanner banner={banner({ color: "#2563eb" })} title="Ravenloft" />
    );
    expect(screen.queryByText("11 members")).not.toBeInTheDocument();

    rerender(
      <PageBanner
        banner={banner({ color: "#2563eb" })}
        title="Ravenloft"
        badges={<span>11 members</span>}
      />
    );
    const corner = screen.getByText("11 members").parentElement as HTMLElement;
    expect(corner.className).toContain("justify-end");
    // Not inside the heading's box — the counts are about the banner, not
    // something it says.
    expect(copy(container)).not.toBe(corner);
  });

  it("gives the badges a row of their own rather than floating them over the copy", () => {
    // An overlay clears the title by luck: in the short band a community with no
    // artwork gets, a long enough name at a narrow enough width wraps straight
    // under it. In flow the copy starts where the corner ended, so there is no
    // width or name that can put them on top of each other.
    const { container } = render(
      <PageBanner
        banner={banner({ color: "#2563eb" })}
        title="The Ancient and Honourable Order of the Silver Ravens"
        badges={<span>11 members</span>}
      />
    );

    const corner = screen.getByText("11 members").parentElement as HTMLElement;
    expect(corner.className).not.toContain("absolute");
    // Same column, corner first: the copy is what is left underneath it.
    expect(corner.parentElement).toBe(column(container));
    expect(corner.nextElementSibling).toBe(copy(container));
    expect(copy(container).className).toContain("flex-1");
  });

  it("covers the banner with the picture rather than letting it set the height", () => {
    // A picture sized to its own 4:1 would stop above a fade's band and leave
    // it empty — a hard edge over nothing, which is not a fade.
    render(
      <PageBanner
        banner={banner({ image_url: "/images/banner.webp", fade: "strong" })}
        title="Ravenloft"
      />
    );

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image.className).toContain("object-cover");
    expect(image.className).toContain("inset-0");
    expect(image.className).toContain("h-full");
  });

  it("spends less height on a fade in a narrow content area", () => {
    // A phone has a page to show under the banner and the least room to show
    // it in, so the dissolve is a fraction of what a laptop's is. The width is
    // the content area's, not the viewport's, so it is measured rather than
    // asked of a media query.
    // The measure only runs inside the shell it measures, so the banner is
    // rendered in one; jsdom reports a zero-width layout, which is narrow.
    const { container } = render(
      <div>
        <main>
          <div>
            <PageBanner banner={banner({ color: "#2563eb", fade: "strong" })} title="Ravenloft" />
          </div>
        </main>
      </div>
    );

    const shellBanner = container.querySelector("main div > div") as HTMLElement;
    expect(shellBanner.style.gridTemplateRows).toBe("auto 96px");
    expect(shellBanner.style.marginBottom).toBe("-96px");
  });
});

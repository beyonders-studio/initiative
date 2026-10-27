import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUserSummary } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";

import { CommentContent } from "./CommentContent";
import { CommentReferences } from "./CommentReferences";

const renderContent = (content: string) =>
  renderWithProviders(<CommentContent content={content} />);

/** Entity mentions render a router `Link`, so they need a mounted router. */
const renderLinkedContent = (content: string) =>
  renderPage(() => <CommentContent content={content} />);

/** A mention of somebody links to them only once the thread has resolved who
 *  they are, which is what `CommentReferences` asks for. */
const renderResolvedContent = (content: string, disableLinks = false) =>
  renderPage(() => (
    <CommentReferences contents={[content]}>
      <CommentContent content={content} disableLinks={disableLinks} />
    </CommentReferences>
  ));

const answerWithPeople = (...people: ReturnType<typeof buildUserSummary>[]) =>
  server.use(
    http.get("*/api/v1/c/:communityId/users/search", () =>
      HttpResponse.json({ items: people, total: people.length, page: 1, page_size: 100 })
    )
  );

describe("CommentContent", () => {
  it("renders markdown inline formatting", () => {
    const { container } = renderContent("Ship **now**, not *later*.");

    expect(container.querySelector("strong")).toHaveTextContent("now");
    expect(container.querySelector("em")).toHaveTextContent("later");
  });

  it("renders lists, headings, and code", () => {
    const { container } = renderContent(
      ["## Plan", "", "- first", "- second", "", "Run `pnpm test` first."].join("\n")
    );

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Plan");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("code")).toHaveTextContent("pnpm test");
  });

  it("renders fenced code blocks without interpreting their contents", () => {
    const { container } = renderContent(["```", "@[Ada](3) **not bold**", "```"].join("\n"));

    const code = container.querySelector("pre code");
    expect(code).toHaveTextContent("@[Ada](3) **not bold**");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("renders GFM tables and strikethrough", () => {
    const { container } = renderContent(
      ["| a | b |", "| - | - |", "| 1 | 2 |", "", "~~dropped~~"].join("\n")
    );

    expect(container.querySelectorAll("th")).toHaveLength(2);
    expect(container.querySelector("del")).toHaveTextContent("dropped");
  });

  it("keeps single newlines as line breaks", () => {
    const { container } = renderContent("one\ntwo");

    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("br")).not.toBeNull();
  });

  it("renders a user mention nobody has resolved as the words it was written with", () => {
    // A profile is addressed by username and number, and a mention stores
    // neither — so there is no link to make until somebody says who id 12 is.
    const { container } = renderContent("thanks @[Ada Lovelace](12)!");

    expect(screen.getByText("@Ada Lovelace")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });

  it("links a mention to the profile of whoever that id is now", async () => {
    answerWithPeople(
      buildUserSummary({ id: 12, username: "ada", discriminator: 7, display_name: "Ada King" })
    );

    renderResolvedContent("thanks @[Ada Lovelace](12)!");

    // Named by who they are today, not by what the comment was written with.
    const link = await screen.findByRole("link", { name: "@Ada King" });
    expect(link).toHaveAttribute("href", "/u/ada0007");
  });

  it("keeps a mention out of a link when the body itself is one", async () => {
    answerWithPeople(
      buildUserSummary({ id: 12, username: "ada", discriminator: 7, display_name: "Ada King" })
    );

    const { container } = renderResolvedContent("thanks @[Ada Lovelace](12)!", true);

    expect(await screen.findByText("@Ada King")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });

  it("names a person stored by id alone as who they are now", async () => {
    answerWithPeople(
      buildUserSummary({ id: 12, username: "ada", discriminator: 7, display_name: "Ada King" })
    );

    renderResolvedContent("thanks @[](12)!");

    const link = await screen.findByRole("link", { name: "@Ada King" });
    expect(link).toHaveAttribute("href", "/u/ada0007");
  });

  it("reads somebody the answer leaves out as a former member, whatever they were called", async () => {
    // Gone from the community, or no account at all: either way the page
    // cannot say who they are, and the name a mention was written with is
    // not who they are now.
    answerWithPeople();

    const { container } = renderResolvedContent("thanks @[](12) and @[Ada Lovelace](13)!");

    // Each mention settles on its own, so both are waited for.
    await waitFor(() => expect(screen.getAllByText("@Former member")).toHaveLength(2));
    expect(container.querySelector("a")).toBeNull();
  });

  it("holds a nameless mention's place until the answer arrives, without guessing", async () => {
    server.use(
      http.get("*/api/v1/c/:communityId/users/search", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      })
    );

    const { container } = renderResolvedContent("thanks @[](12) and @[Ada Lovelace](13)!");

    // Older text still carries a name, which stands in meanwhile.
    expect(await screen.findByText("@Ada Lovelace")).toBeInTheDocument();
    expect(container).toHaveTextContent("thanks @… and @Ada Lovelace!");
    expect(screen.queryByText(/Former member/)).not.toBeInTheDocument();
  });

  it("stops waiting once the lookup gives up, without guessing", async () => {
    server.use(
      http.get("*/api/v1/c/:communityId/users/search", () => HttpResponse.json({}, { status: 500 }))
    );

    renderResolvedContent("thanks @[](12)!");

    expect(await screen.findByTitle("Couldn't load this name")).toHaveTextContent("…");
    expect(screen.queryByText(/Former member/)).not.toBeInTheDocument();
  });

  it("keeps the name of somebody with no account, who has nothing else to go by", () => {
    // One an export could not name has neither, and reads as a former member.
    const { container } = renderContent("thanks @[Ada Lovelace]() and @[]()!");

    expect(screen.getByText("@Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("@Former member")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });

  it("links task, doc, and project mentions", async () => {
    renderLinkedContent("#task[Fix login](3) #file[Runbook](4) #project[Apollo](5)");

    expect(await screen.findByRole("link", { name: /Fix login/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Runbook/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Apollo/ })).toBeInTheDocument();
  });

  it("keeps a mention rendered beside its surrounding markdown", async () => {
    const { container } = renderLinkedContent("**Heads up** @[Ada](12) — see #task[Fix login](3)");

    expect(await screen.findByRole("link", { name: /Fix login/ })).toBeInTheDocument();
    expect(container.querySelector("strong")).toHaveTextContent("Heads up");
    expect(screen.getByText("@Ada")).toBeInTheDocument();
  });

  it("leaves an ordinary numeric-target link alone", () => {
    renderContent("see [the docs](https://example.com/12)");

    const link = screen.getByRole("link", { name: "the docs" });
    expect(link).toHaveAttribute("href", "https://example.com/12");
  });

  it("autolinks bare urls and opens them in a new tab", () => {
    renderContent("docs at https://example.com/guide");

    const link = screen.getByRole("link", { name: /example\.com/ });
    expect(link).toHaveAttribute("href", "https://example.com/guide");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("shows an image as a link instead of loading it", () => {
    const { container } = renderContent("![a diagram](https://example.com/pic.png)");

    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "a diagram" });
    expect(link).toHaveAttribute("href", "https://example.com/pic.png");
  });

  it("names an image by its address when it has no alt text", () => {
    renderContent("![](https://example.com/pic.png)");

    expect(screen.getByRole("link", { name: "https://example.com/pic.png" })).toBeInTheDocument();
  });

  it.each([
    ["directly", "[![diagram](https://example.com/pic.png)](https://example.com/details)"],
    [
      "under formatting",
      "[**![diagram](https://example.com/pic.png)**](https://example.com/details)",
    ],
    [
      "by reference",
      "[![diagram][pic]](https://example.com/details)\n\n[pic]: https://example.com/pic.png",
    ],
  ])("keeps an author's destination when they linked an image %s", (_case, markdown) => {
    const { container } = renderContent(markdown);

    expect(container.querySelector("img")).toBeNull();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://example.com/details");
    expect(links[0]).toHaveTextContent("diagram");
  });

  it("links a reference-style image to its definition", () => {
    renderContent("![diagram][pic]\n\n[pic]: https://example.com/pic.png");

    expect(screen.getByRole("link", { name: "diagram" })).toHaveAttribute(
      "href",
      "https://example.com/pic.png"
    );
  });

  it("does not render raw html", () => {
    const { container } = renderContent('<img src=x onerror="alert(1)"> <b>plain</b>');

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});

describe("pictures in a comment", () => {
  it("shows a picture stored here", () => {
    const { container } = renderContent("Look: ![shot](/uploads/9/pasted-a.png)");

    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "/uploads/9/pasted-a.png");
    expect(img).toHaveAttribute("alt", "shot");
  });

  it("turns a picture from anywhere else into a link, so reading fetches nothing", () => {
    const { container } = renderContent("![pixel](https://tracker.example/p.gif)");

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "pixel" })).toHaveAttribute(
      "href",
      "https://tracker.example/p.gif"
    );
  });

  it("names a stored picture in a clamped preview rather than drawing it", () => {
    const { container } = renderWithProviders(
      <CommentContent content="![shot](/uploads/9/pasted-a.png)" compact />
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("shot")).toBeInTheDocument();
  });

  it("opens a stored picture full size", async () => {
    const user = userEvent.setup();
    renderContent("![shot](/uploads/9/pasted-a.png)");

    await user.click(screen.getByRole("button", { name: "View shot full size" }));

    expect(
      within(screen.getByRole("dialog")).getByRole("img", { name: "shot" })
    ).toBeInTheDocument();
  });

  it("leaves the click to the link when the body sits inside one", () => {
    renderWithProviders(<CommentContent content="![shot](/uploads/9/pasted-a.png)" disableLinks />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "shot" })).toBeInTheDocument();
  });
});

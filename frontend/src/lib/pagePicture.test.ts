import { describe, expect, it } from "vitest";

import { findPeople, partKindOf, showPeople } from "./pagePicture";

const words = {
  you: "You",
  person: (number: number) => `Person ${number}`,
  email: "email hidden",
  phone: "number hidden",
};

const page = (html: string) => {
  const root = document.createElement("div");
  root.innerHTML = html;
  return root;
};

const people = new Map([
  [1, new Set(["Ireena Kolyana", "ireena#0001", "ireena"])],
  [2, new Set(["Ismark", "ismark#0002"])],
  [3, new Set(["Ezmerelda"])],
]);

describe("findPeople", () => {
  it("swaps each person for the same stand-in wherever they are, and the sender for You", () => {
    const root = page(
      `<b>Ismark</b><p>Ezmerelda asked Ismark, and ireena#0001 answered.</p><span>Ireena Kolyana</span>`
    );
    const found = findPeople(root, people, 1, words);
    showPeople(found, true, "grey");

    expect(root.textContent).toBe("Person 1Person 2 asked Person 1, and You answered.You");
    expect(found.people).toBe(2);
  });

  it("swaps a name only where it stands as a word", () => {
    const root = page("<p>Ismarkian cookies, for Ismark.</p>");
    showPeople(findPeople(root, people, null, words), true, "grey");
    expect(root.textContent).toBe("Ismarkian cookies, for Person 1.");
  });

  it("hides emails and phone numbers, and leaves dates and amounts", () => {
    const root = page(
      "<p>Write to a.b@example.org or call 0412 555 019 or +1 (555) 010-9999 by 2026-11-07 for 1,250.</p>"
    );
    const found = findPeople(root, new Map(), null, words);
    showPeople(found, true, "grey");
    expect(root.textContent).toBe(
      "Write to email hidden or call number hidden or number hidden by 2026-11-07 for 1,250."
    );
    expect([found.emails, found.phones]).toEqual([1, 2]);
  });

  it("puts everything back when people are shown again", () => {
    const root = page(
      '<span data-slot="avatar" style="color: red"><img alt=""></span><b>Ismark</b>'
    );
    const found = findPeople(root, people, null, words);
    showPeople(found, true, "grey");
    expect(root.querySelector("img")).toBeNull();
    showPeople(found, false, "grey");
    expect(root.querySelector("img")).not.toBeNull();
    expect(root.querySelector('[data-slot="avatar"]')?.getAttribute("style")).toBe("color: red");
    expect(root.textContent).toBe("Ismark");
  });

  it("names the part a name, an email or a number is", () => {
    const root = page("<b>Ismark</b><i>a@example.org</i><p>Ismark wrote this.</p>");
    findPeople(root, people, null, words);
    const [name, email, paragraph] = Array.from(root.children);
    expect([partKindOf(name), partKindOf(email), partKindOf(paragraph)]).toEqual([
      "name",
      "email",
      "text",
    ]);
  });
});

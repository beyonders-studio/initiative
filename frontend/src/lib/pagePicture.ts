/**
 * A picture of the page somebody is on, to send with a ticket.
 *
 * The page is drawn into an SVG that holds a copy of it, laid out like the
 * page (`modern-screenshot`). The picture editor shows that copy as it is, so
 * people can be swapped for stand-ins and the page's parts found on the copy;
 * the page itself never changes. Attaching draws the copy into a PNG.
 */

import { queryClient } from "@/lib/queryClient";
import { type DisplayableUser, getUserHandle } from "@/lib/userDisplay";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The page, drawn: an SVG of its size holding a copy of it. */
export interface PagePicture {
  svg: SVGSVGElement;
  width: number;
  height: number;
}

/**
 * Draw what is on screen, leaving out `leaveOut` (the panel the picture is
 * taken from), the overlay a sheet lays over the page, and any toasts.
 */
export const pictureThePage = async (leaveOut: Element | null): Promise<PagePicture> => {
  const { domToForeignObjectSvg } = await import("modern-screenshot");
  const width = window.innerWidth;
  const height = window.innerHeight;
  const svg = (await domToForeignObjectSvg(document.body, {
    width,
    height,
    backgroundColor: getComputedStyle(document.body).backgroundColor,
    filter: (node) =>
      !(node instanceof Element) ||
      (node !== leaveOut && !node.matches('[data-slot="sheet-overlay"], [data-sonner-toaster]')),
    features: { restoreScrollPosition: true },
  })) as SVGSVGElement;
  return { svg, width, height };
};

/** Draw `svg` as an image, as it is now. */
export const svgImage = (svg: SVGSVGElement): Promise<HTMLImageElement> =>
  new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The picture could not be drawn."));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
      new XMLSerializer().serializeToString(svg)
    )}`;
  });

// ---------------------------------------------------------------------------
// The page's parts

/** What a part of the page is, as the editor names it. */
export type PartKind =
  | "name"
  | "avatar"
  | "email"
  | "phone"
  | "picture"
  | "field"
  | "button"
  | "link"
  | "heading"
  | "row"
  | "item"
  | "card"
  | "text";

/** The elements that make a part, each with what it is. The first that
 *  matches names it. */
const PART_KINDS: [string, PartKind][] = [
  ['[data-slot="avatar"]', "avatar"],
  ["img, canvas, video", "picture"],
  ['input, textarea, select, [contenteditable="true"]', "field"],
  ['button, [role="button"]', "button"],
  ["a[href]", "link"],
  ["h1, h2, h3, h4, h5, h6", "heading"],
  ['tr, [role="row"]', "row"],
  ['li, [role="listitem"], article', "item"],
  ['[data-slot="card"]', "card"],
  ["p, label, td, th, dd, dt, blockquote, pre", "text"],
];

/** Every element that is a part of the page. */
export const PART_SELECTOR = [
  "[data-picture-part]",
  ...PART_KINDS.map(([selector]) => selector),
].join(", ");

/** What ``element`` is, as a part of the page. */
export const partKindOf = (element: Element): PartKind => {
  const marked = element.getAttribute("data-picture-part");
  if (marked) return marked as PartKind;
  return PART_KINDS.find(([selector]) => element.matches(selector))?.[1] ?? "text";
};

// ---------------------------------------------------------------------------
// People

/** Every way the app has loaded of naming each person: their display name,
 *  their handle, their username and their email, by their id. ``also`` adds
 *  people held outside the query cache, such as whoever is signed in. */
export const loadedPeople = (also: unknown[] = []): Map<number, Set<string>> => {
  const people = new Map<number, Set<string>>();
  const seen = new WeakSet<object>();
  const visit = (value: unknown, depth: number) => {
    if (depth > 10 || !value || typeof value !== "object" || seen.has(value)) return;
    seen.add(value);
    const record = value as Record<string, unknown>;
    const id = typeof record.id === "number" ? record.id : record.user_id;
    if (typeof id === "number" && typeof record.username === "string") {
      const user = record as DisplayableUser;
      const names = people.get(id) ?? new Set<string>();
      for (const name of [user.display_name, getUserHandle(user), user.username, record.email]) {
        if (typeof name === "string" && name.trim().length > 1) names.add(name.trim());
      }
      people.set(id, names);
    }
    for (const child of Object.values(record)) visit(child, depth + 1);
  };
  for (const query of queryClient.getQueryCache().getAll()) visit(query.state.data, 0);
  for (const person of also) visit(person, 0);
  return people;
};

/** The words a stand-in is written in. */
export interface StandInWords {
  you: string;
  person: (number: number) => string;
  email: string;
  phone: string;
}

/** Who and what on the page is swapped for a stand-in, and what was there. */
export interface PeopleOnPage {
  texts: { node: Text; original: string; standIn: string }[];
  avatars: { element: HTMLElement; html: string; style: string | null }[];
  people: number;
  emails: number;
  phones: number;
}

const EMAIL = /[^\s@<>()"]+@[^\s@<>()"]+\.[A-Za-z]{2,}/g;
// A number written as a phone number is: a leading +, or three groups of
// digits split by spaces, dots or dashes. A date or an amount is neither.
const PHONE = /\+\d[\d ().-]{6,}\d|\(?\b\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}\b/g;
const literal = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Find the people on the page in ``root``: the names `people` holds, emails
 * and phone numbers in its text, and every avatar. Nothing is swapped until
 * {@link showPeople} says so. A text that is only a name, an email or a phone
 * number is marked as that part, so the editor can name it.
 */
export const findPeople = (
  root: Element,
  people: Map<number, Set<string>>,
  me: number | null,
  words: StandInWords
): PeopleOnPage => {
  const ids = new Map<string, number>();
  for (const [id, names] of people) for (const name of names) ids.set(name.toLowerCase(), id);
  // Longest first, so a handle is swapped whole before the username in it.
  const names = [...ids.keys()].sort((a, b) => b.length - a.length);
  const named = names.length
    ? new RegExp(
        `(?<![\\p{L}\\p{N}_])(?:${names.map(literal).join("|")})(?![\\p{L}\\p{N}_])`,
        "giu"
      )
    : null;
  const numbers = new Map<number, number>();
  const standInFor = (id: number) => {
    if (id === me) return words.you;
    if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
    return words.person(numbers.get(id) ?? 0);
  };

  const found: PeopleOnPage = { texts: [], avatars: [], people: 0, emails: 0, phones: 0 };
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const original = node.data;
    // The kind of the last thing swapped, kept when it was the whole text.
    const part: { kind: PartKind | null } = { kind: null };
    const whole = (match: string, kind: PartKind) => {
      part.kind = match.trim() === original.trim() ? kind : null;
    };
    let standIn = original.replace(EMAIL, (match) => {
      found.emails += 1;
      whole(match, "email");
      return words.email;
    });
    standIn = standIn.replace(PHONE, (match) => {
      found.phones += 1;
      whole(match, "phone");
      return words.phone;
    });
    if (named) {
      standIn = standIn.replace(named, (match) => {
        whole(match, "name");
        return standInFor(ids.get(match.toLowerCase()) ?? -1);
      });
    }
    if (standIn === original) continue;
    found.texts.push({ node, original, standIn });
    // A text that is only a name, an email or a number: the element holding
    // nothing else is that part of the page.
    const parent = node.parentElement;
    if (part.kind && parent && parent.textContent?.trim() === original.trim()) {
      parent.setAttribute("data-picture-part", part.kind);
    }
  }
  for (const element of root.querySelectorAll<HTMLElement>('[data-slot="avatar"]')) {
    found.avatars.push({ element, html: element.innerHTML, style: element.getAttribute("style") });
  }
  found.people = numbers.size;
  return found;
};

/** Swap the people on the page for their stand-ins, or put them back. An
 *  avatar's stand-in is a plain circle of ``blank``. */
export const showPeople = (found: PeopleOnPage, hidden: boolean, blank: string) => {
  for (const text of found.texts) text.node.data = hidden ? text.standIn : text.original;
  for (const avatar of found.avatars) {
    if (hidden) {
      avatar.element.innerHTML = "";
      avatar.element.style.background = blank;
    } else {
      avatar.element.innerHTML = avatar.html;
      if (avatar.style === null) avatar.element.removeAttribute("style");
      else avatar.element.setAttribute("style", avatar.style);
    }
  }
};

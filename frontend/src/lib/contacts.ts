/**
 * A contact's details, as the pages that show and edit them read them.
 *
 * A contact holds four lists of labelled values, each shown first-first: the
 * first phone is the one a table shows and a chip reads. The links here are
 * what makes a value one tap from a call or a message.
 */

import {
  type ContactDetail,
  type ContactRead,
  EndpointKind,
  type RelatedEnd,
  type RelationshipRead,
  RelationshipType,
  SmartChipAspect,
} from "@/api/generated/initiativeAPI.schemas";

/** The lists a contact holds, in the order a card shows them. */
export const CONTACT_DETAILS = ["phones", "emails", "addresses", "websites"] as const;

export type ContactDetailField = (typeof CONTACT_DETAILS)[number];

/** A contact's details, as an editor holds them. */
export type ContactDetails = Pick<ContactRead, ContactDetailField>;

export const NO_DETAILS: ContactDetails = { phones: [], emails: [], addresses: [], websites: [] };

/** The labels offered while one is typed (`contacts:labels.*`); any other is fine. */
export const DETAIL_LABELS = {
  phones: ["mobile", "work", "home", "office", "main"],
  emails: ["work", "home", "billing", "other"],
  addresses: ["office", "home", "billing", "venue"],
  websites: ["work", "booking", "other"],
} as const satisfies Record<ContactDetailField, readonly string[]>;

/** A detail with nothing in it, as a row being added holds one. */
export const BLANK_DETAIL: ContactDetail = { label: "", value: "" };

/** What a save sends: the rows with a value, trimmed. */
export const filledDetails = (details: ContactDetails): ContactDetails =>
  Object.fromEntries(
    CONTACT_DETAILS.map((field) => [
      field,
      details[field]
        .map((detail) => ({ label: (detail.label ?? "").trim(), value: detail.value.trim() }))
        .filter((detail) => detail.value !== ""),
    ])
  ) as ContactDetails;

/** A number as a phone dials it: digits and a leading plus, and an extension
 *  written after an `x` as the dialler's own `;ext=`. */
export const telHref = (value: string): string => {
  const [number, extension] = value.split(/x/i);
  const digits = number.replace(/[^\d+]/g, "");
  const ext = extension?.replace(/\D/g, "");
  return `tel:${digits}${ext ? `;ext=${ext}` : ""}`;
};

export const mailtoHref = (value: string): string => `mailto:${value}`;

/** Where a chip's reading takes a tap: its phone dials and its email writes.
 *  Every other fact opens the thing it is about. */
export const chipReachHref = (aspect: string, value: string): string | null =>
  aspect === SmartChipAspect.phone
    ? telHref(value)
    : aspect === SmartChipAspect.email
      ? mailtoHref(value)
      : null;

const isPartOf = (row: RelationshipRead, direction: "inbound" | "outbound") =>
  row.relationship_type === RelationshipType.part_of &&
  row.direction === direction &&
  row.other.type === EndpointKind.contact;

/** The organization a person is part of: the contact at the far end of their
 *  `part_of` link. A person has one, if any; the first is the one shown. */
export const organizationOf = (rows: readonly RelationshipRead[]): RelatedEnd | null =>
  rows.find((row) => isPartOf(row, "outbound"))?.other ?? null;

/** The people part of an organization, by name. */
export const peopleOf = (rows: readonly RelationshipRead[]): RelatedEnd[] =>
  rows
    .filter((row) => isPartOf(row, "inbound"))
    .map((row) => row.other)
    .sort((a, b) => (a.title ?? "").localeCompare(b.title ?? ""));

/** Each far end once, however many links reach it. */
const distinct = (ends: RelatedEnd[]): RelatedEnd[] => {
  const seen = new Set<string>();
  return ends.filter((end) => {
    const key = `${end.type}:${end.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

/** Where things stand with a contact, read from its links rather than kept on
 *  it: what is still open, what is coming up (soonest first), and its files. */
export interface ContactStanding {
  openTasks: RelatedEnd[];
  upcoming: RelatedEnd[];
  files: RelatedEnd[];
}

export const standingOf = (rows: readonly RelationshipRead[], now: Date): ContactStanding => {
  const ends = distinct(rows.map((row) => row.other));
  return {
    openTasks: ends.filter((end) => end.type === EndpointKind.task && end.is_open === true),
    upcoming: ends
      .filter(
        (end) =>
          end.type === EndpointKind.calendar_event &&
          end.starts_at !== null &&
          new Date(end.starts_at) >= now
      )
      .sort((a, b) => new Date(a.starts_at ?? 0).getTime() - new Date(b.starts_at ?? 0).getTime()),
    files: ends.filter((end) => end.type === EndpointKind.file),
  };
};

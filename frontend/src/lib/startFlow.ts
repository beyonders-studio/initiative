/**
 * What the start flow asks, kept between screens and across a reload, and the
 * starter content it makes once somebody is signed in to make it for.
 *
 * Nothing here reaches the server before the account exists. The answers live
 * in this browser until then; an account that cannot sign in yet (its address
 * still unconfirmed) leaves them waiting, and the first signed-in load on this
 * browser finishes the job.
 */

import type { CommunityCategory, NewCommunity } from "@/api/generated/initiativeAPI.schemas";
import { createInitiative } from "@/api/generated/initiatives/initiatives";
import { createProject } from "@/api/generated/projects/projects";
import { invalidate, q } from "@/api/query-keys";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import type { CommunityEntry } from "@/hooks/useCommunities";
import { asCommunityCategories } from "@/lib/communityCategories";
import { EMPTY_PLACE, type Place, placeFrom } from "@/lib/directoryNear";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { browserTimezone } from "@/ui/lib/timezones";

export type StartPath = "invite" | "join" | "personal" | "shared";

export interface StartAnswers {
  path: StartPath;
  inviteCode: string;
  /** Join: the directory shelves to open on; none opens all of them. */
  categories: CommunityCategory[];
  /** Join: where they are, to open the directory nearest them first. */
  near: Place;
  communityName: string;
  description: string;
  initiativeName: string;
  /** Personal: the task project they land on. */
  listName: string;
  /** Shared, where plans are offered: the catalog tier picked. */
  planId: string | null;
  /** The name part of their handle. */
  username: string;
  timezone: string;
}

const DRAFT_KEY = "initiative-start-draft";
const PENDING_KEY = "initiative-start-pending";

export const freshAnswers = (path: StartPath, inviteCode = ""): StartAnswers => ({
  path,
  inviteCode,
  categories: [],
  near: EMPTY_PLACE,
  communityName: "",
  description: "",
  initiativeName: "",
  listName: "",
  planId: null,
  username: "",
  timezone: browserTimezone(),
});

const parse = <T>(raw: string | null): T | null => {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
};

/** Answers as saved, on today's shape: anything a saved copy lacks or holds
 *  in an older form starts empty. */
const current = (saved: StartAnswers | null): StartAnswers | null => {
  if (!saved?.path) return null;
  return {
    ...freshAnswers(saved.path),
    ...saved,
    categories: asCommunityCategories(saved.categories),
    username: typeof saved.username === "string" ? saved.username : "",
    near: placeFrom(saved.near),
  };
};

export const readStartDraft = (): StartAnswers | null =>
  current(parse<StartAnswers>(getItem(DRAFT_KEY)));

export const saveStartDraft = (answers: StartAnswers): void => {
  void setItem(DRAFT_KEY, JSON.stringify(answers));
};

interface PendingStart {
  email: string;
  answers: StartAnswers;
  /** The page that sent them to sign up, such as a plug-in's sign-in. */
  next?: string;
}

const readPending = (email: string): PendingStart | null => {
  const pending = parse<PendingStart>(getItem(PENDING_KEY));
  return pending && pending.email === email.toLowerCase() ? pending : null;
};

/** Leave the answers, and where to land after, for the first signed-in load
 *  of the account `email`. */
export const savePendingStart = async (
  email: string,
  answers: StartAnswers,
  next?: string | null
): Promise<void> => {
  await setItem(
    PENDING_KEY,
    JSON.stringify({ email: email.toLowerCase(), answers, ...(next ? { next } : {}) })
  );
};

/** The answers left for this account, if any were. */
export const readPendingStart = (email: string): StartAnswers | null =>
  current(readPending(email)?.answers ?? null);

/** Where the start left for this account lands, when a page sent them to it. */
export const readPendingNext = (email: string): string | null => readPending(email)?.next ?? null;

export const clearStart = async (): Promise<void> => {
  await Promise.all([removeItem(DRAFT_KEY), removeItem(PENDING_KEY)]);
};

/** The community a sign-up sends for these answers, or none. */
export const newCommunity = (answers: StartAnswers): NewCommunity | undefined => {
  if (answers.path !== "personal" && answers.path !== "shared") return undefined;
  const description = answers.description.trim();
  return {
    name: answers.communityName.trim(),
    ...(description ? { description } : {}),
  };
};

/** The community a registration made from these answers: the newest one of
 *  that name the account belongs to. */
export const findStartedCommunity = (
  communities: CommunityEntry[],
  answers: StartAnswers
): CommunityEntry | undefined =>
  communities
    .filter(
      (community) =>
        community.accessType !== "grant" && community.name === answers.communityName.trim()
    )
    .sort((a, b) => b.id - a.id)[0];

export interface Starter {
  initiativeId: number;
  /** Personal only. */
  projectId: number | null;
}

/** The first initiative, and for Personal its task project, through the same
 *  endpoints the initiative wizard and the project dialog call. */
export const seedStarter = async (communityId: number, answers: StartAnswers): Promise<Starter> => {
  const initiative = await createInitiative(communityId, {
    name: answers.initiativeName.trim(),
  });
  let projectId: number | null = null;
  if (answers.path === "personal") {
    const project = await createProject(communityId, {
      name: answers.listName.trim(),
      initiative_id: initiative.id,
      grants: [...DEFAULT_GRANTS],
    });
    projectId = project.id;
  }
  void invalidate(q.allInitiatives(), q.allProjects());
  return { initiativeId: initiative.id, projectId };
};

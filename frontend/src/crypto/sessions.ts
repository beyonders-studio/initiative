/** The account and sessions this device holds, and the only ways they move. */

import {
  claimOwnSessionKeys,
  claimSessionKeys,
} from "@/api/generated/direct-messages/direct-messages";
import type { DmOneTimeKeyUpload } from "@/api/generated/initiativeAPI.schemas";

import { ratchet } from "./client";
import {
  accountPickle,
  allSessions,
  type SessionOrigin,
  sessionAuthor,
  sessionDevice,
  sessionForDevice,
  sessionOrigin,
  sessionPickle,
  sessionsInConversation,
} from "./store";
import type { TrustedDevice } from "./trust";
import type { Decrypted, InboundSession } from "./types";

/** How many times a key-store write is retried when another tab moves it first. */
const WRITE_ATTEMPTS = 3;

/**
 * One destination for a message: a device the trust seam returned, and which
 * side of the conversation it is on.
 */
export type Destination = TrustedDevice & { origin: SessionOrigin };

/**
 * Why a queued message was not read: it is from a device of this account's
 * that is waiting to be verified, it is one nothing here will ever open, or it
 * could not be tried this time.
 */
export type Unread = "waiting" | "unreadable" | "retry";

/** One queued message read, and what its session says about who sent it. */
export interface Received {
  plaintext: string;
  mine: boolean;
  author?: number;
  /** The device on the other end, where the session recorded it. */
  device?: string;
}

type Work<T> = (pickle: string) => Promise<{ next: string; value: T } | null>;

/**
 * Advance a pickle, and only keep the result if nobody else moved it first.
 *
 * Every ratchet step is a read and a write, from any number of tabs: the
 * account spends a prekey on each inbound session and mints fifty on a top-up,
 * and a session moves on with every message either way. Two tabs starting from
 * the same pickle both write, and the one that lands second undoes the other --
 * losing the private halves of published keys, or leaving a message the far end
 * has no state to open. So a writer that loses redoes its work against what is
 * stored.
 *
 * `work` returns `null` for "there is nothing I can do with this", and so does
 * this: a pickle that is not there, or a caller that never gets its turn, is
 * the same answer.
 */
async function advance<T>(
  get: () => Promise<string | undefined>,
  swap: (expected: string, next: string) => Promise<boolean>,
  work: Work<T>
): Promise<T | null> {
  for (let attempt = 0; attempt < WRITE_ATTEMPTS; attempt += 1) {
    const current = await get();
    if (!current) return null;
    const done = await work(current);
    if (done === null) return null;
    if (await swap(current, done.next)) return done.value;
  }
  return null;
}

export const withAccount = <T>(work: Work<T>) =>
  advance(accountPickle.get, accountPickle.swap, work);

export const withSession = <T>(sessionId: string, work: Work<T>) =>
  advance(
    () => sessionPickle.get(sessionId),
    (expected, next) => sessionPickle.swap(sessionId, expected, next),
    work
  );

/** The session already held with a device, if it is still usable. */
export async function establishedSession(deviceId: string): Promise<string | null> {
  const known = await sessionForDevice.get(deviceId);
  if (!known) return null;
  return (await sessionPickle.get(known)) ? known : null;
}

/**
 * Write down a session that has just been opened.
 *
 * Which end it belongs to and whose device it is are knowable now and never
 * again: an ordinary message arriving on it later names no sender. The device
 * is what a reply looks up, so an answer does not open a second session and
 * spend another of their prekeys; and it joins the conversation's list, since
 * the other party may have several devices, each its own ratchet.
 */
async function keepSession(
  conversationId: string,
  destination: Destination,
  sessionId: string,
  pickle: string
): Promise<void> {
  await sessionPickle.set(sessionId, pickle);
  await sessionOrigin.set(sessionId, destination.origin);
  // A log does not name the person keeping it, so this account's own sessions
  // carry no author.
  if (destination.origin === "other") {
    await sessionAuthor.set(sessionId, destination.userId);
  }
  await sessionDevice.set(sessionId, destination.id);
  await sessionForDevice.set(destination.id, sessionId);
  await sessionsInConversation.add(conversationId, sessionId);
  await allSessions.add(sessionId);
}

/**
 * Open a session with a device on a one-time key claimed from it. The ratchet
 * checks the key's signature against the device's fingerprint key.
 */
export async function openOutboundSession(
  conversationId: string,
  destination: Destination,
  oneTimeKey: DmOneTimeKeyUpload
): Promise<string> {
  const account = await accountPickle.get();
  if (!account) throw new Error("this device has no key store");
  const session = await ratchet.createOutboundSession(
    account,
    destination.identityKey,
    destination.fingerprintKey,
    oneTimeKey.public_key,
    oneTimeKey.signature,
    oneTimeKey.fallback ?? false
  );
  await keepSession(conversationId, destination, session.session_id, session.session_pickle);
  return session.session_id;
}

/**
 * Read one message on one held session, filing the session under the
 * conversation so the next message on it is found straight away.
 */
async function readOn(
  sessionId: string,
  item: { conversation_id: string; message_type: number; payload: string }
): Promise<Received | Unread> {
  const decrypted = await withSession<Decrypted | false>(sessionId, async (pickle) => {
    const out = await ratchet.decrypt(pickle, item.message_type, item.payload);
    // Refused, and the session is left as it was: written back unchanged so
    // the answer is this session's, not a write that lost to another tab.
    return out ? { next: out.session_pickle, value: out } : { next: pickle, value: false as const };
  }).catch(() => null);
  if (decrypted === null) return "retry";
  if (decrypted === false) return "unreadable";
  await sessionsInConversation.add(item.conversation_id, sessionId);
  return {
    plaintext: decrypted.plaintext,
    mine: (await sessionOrigin.get(sessionId)) === "self",
    author: await sessionAuthor.get(sessionId),
    device: await sessionDevice.get(sessionId),
  };
}

/**
 * Read a pre-key message.
 *
 * The message names the session it belongs to and the identity that wrote it.
 * A sender goes on marking its messages as pre-key until it hears back, so a
 * session this device already holds is the usual answer. A new one is opened
 * with the one device the identity belongs to, found through the trust seam. Opening one spends a prekey out of the account, so it goes
 * through the same compare-and-swap as everything else that advances it.
 */
export async function readPreKey(
  item: { conversation_id: string; message_type: number; payload: string },
  senderOf: (identityKey: string) => Promise<Destination | Unread>
): Promise<Received | Unread> {
  const named = await ratchet.inspectPreKey(item.payload).catch(() => undefined);
  if (named === undefined) return "retry";
  if (named === null) return "unreadable";
  if (await sessionPickle.get(named.session_id)) return readOn(named.session_id, item);
  const sender = await senderOf(named.identity_key);
  if (typeof sender === "string") return sender;
  // A prekey this account no longer holds -- spent on this same message
  // already, or never its own -- is refused, and stays refused.
  const session = await withAccount<InboundSession | false>(async (pickle) => {
    const opened = await ratchet.createInboundSession(pickle, sender.identityKey, item.payload);
    return opened
      ? { next: opened.account_pickle, value: opened }
      : { next: pickle, value: false as const };
  }).catch(() => null);
  if (session === null) return "retry";
  if (session === false) return "unreadable";
  await keepSession(item.conversation_id, sender, session.session_id, session.session_pickle);
  return {
    plaintext: session.plaintext,
    mine: sender.origin === "self",
    ...(sender.origin === "other" ? { author: sender.userId } : {}),
    device: sender.id,
  };
}

/**
 * Claim one prekey from each device that still needs a session opened with it.
 *
 * Claiming spends a key, so it is asked for only where there is nothing to
 * carry the message yet, and only for those devices. An established
 * conversation therefore costs neither side a prekey, however many messages it
 * carries. A one-time key is taken only with its signature on it.
 */
export async function claimKeysFor(
  missing: Destination[],
  ownDeviceId: string
): Promise<Map<string, DmOneTimeKeyUpload>> {
  const byAccount = new Map<number, Destination[]>();
  for (const destination of missing.filter((d) => d.origin === "other")) {
    byAccount.set(destination.userId, [...(byAccount.get(destination.userId) ?? []), destination]);
  }
  const idsOf = (destinations: Destination[]) => destinations.map((destination) => destination.id);
  const claims = [...byAccount].map(([userId, destinations]) =>
    claimSessionKeys(userId, { device_ids: idsOf(destinations) })
  );
  const ours = missing.filter((destination) => destination.origin === "self");
  if (ours.length > 0) {
    claims.push(claimOwnSessionKeys({ device_id: ownDeviceId, device_ids: idsOf(ours) }));
  }
  const keys = new Map<string, DmOneTimeKeyUpload>();
  // Settled rather than all: a claim can be refused after the directory was
  // read -- somebody's permission changes in between -- and one refusal must
  // not take the members whose keys did come back with it. A destination whose
  // key is missing is skipped further down, which is what a member with nothing
  // to open a session on already gets.
  for (const settled of await Promise.allSettled(claims)) {
    if (settled.status !== "fulfilled") continue;
    for (const device of settled.value.devices) {
      const key = device.one_time_key;
      if (key?.signature) {
        keys.set(device.device_id, key);
      }
    }
  }
  return keys;
}

/**
 * Read one ordinary message with a session this device already holds.
 *
 * Which device sent it is not on the row, so the conversation's own sessions
 * are tried first, and then the others that could be carrying it: this
 * account's own, which are in every conversation, and those with somebody on
 * this conversation's roster.
 */
export async function readWithHeldSession(
  item: { conversation_id: string; message_type: number; payload: string },
  roster: ReadonlySet<number>
): Promise<Received | Unread> {
  // An ordinary message only follows a reply on its session, so the session it
  // was written on is already here: one that none of them opens never will be
  // opened, unless a session could not be tried.
  let untried = false;
  const attempt = async (sessionId: string) => {
    const read = await readOn(sessionId, item);
    if (read === "retry") untried = true;
    return typeof read === "string" ? null : read;
  };
  const here = await sessionsInConversation.get(item.conversation_id);
  for (const sessionId of here) {
    const read = await attempt(sessionId);
    if (read) return read;
  }
  for (const sessionId of await allSessions.get()) {
    if (here.includes(sessionId)) continue;
    const author = await sessionAuthor.get(sessionId);
    const ours = (await sessionOrigin.get(sessionId)) === "self";
    if (!ours && (author === undefined || !roster.has(author))) continue;
    const read = await attempt(sessionId);
    if (read) return read;
  }
  return untried ? "retry" : "unreadable";
}

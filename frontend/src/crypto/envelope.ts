/**
 * What one message carries, and what arriving does with it.
 *
 * The envelope carries an id of its own, which is what a receipt names: the
 * local id never leaves this device, and the queue row's id belongs to one
 * recipient device. The version is here because a message already sent cannot
 * be rewritten, so anything a later reader needs has to be in the first one.
 *
 * Every kind is declared once, in `KINDS`: how it is read, which sessions it is
 * taken from, and what it changes on this device.
 */

import {
  historyAsk,
  messageLog,
  pendingHistoryRequest,
  type ReceiptState,
  type SessionOrigin,
  type StoredMessage,
  threadCatchUp,
} from "./store";
import type { TrustedDevice } from "./trust";

/** One message out of the ratchet, and what its session says about who sent it. */
export interface Arrival {
  conversationId: string;
  /** When the server queued it, for an envelope that carries no time of its own. */
  createdAt: string;
  /** Whether it came on a session with one of this account's own devices. */
  mine: boolean;
  author?: number;
  /** The device its session is with, where the session recorded it. */
  device?: string;
}

/** What one collection gathers from the envelopes it reads. */
export interface Batch {
  /** This account's confirmed devices. */
  own: TrustedDevice[];
  /** Their messages that reached this device, per conversation, to report. */
  landed: Map<string, string[]>;
  /** Members who have just joined a group and asked for its thread. */
  asking: { conversationId: string; requestId: string; userId: number }[];
}

type Raw = Record<string, unknown>;

/**
 * One kind of envelope.
 *
 * `parse` returns the fields the kind needs, or `null` for one that is
 * half-written. `from` is which sessions it is taken from; one that arrives on
 * any other is taken off the server and does nothing. `handle` answers the
 * conversation whose thread it changed, if any.
 */
export interface KindSpec<F> {
  parse: (raw: Raw) => F | null;
  from: SessionOrigin | "any";
  // Method syntax, so every kind can be dispatched as a `KindSpec<unknown>`.
  handle(fields: F, arrival: Arrival, batch: Batch): Promise<string | undefined>;
}

/** Declares one kind, so its fields are inferred from its parser. */
const kind = <F>(spec: KindSpec<F>): KindSpec<F> => spec;

/** One entry of a thread, with the two fields everything else is hung off. */
const isStoredMessage = (value: unknown): value is StoredMessage => {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.id === "string" &&
    typeof entry.at === "string" &&
    typeof entry.body === "string" &&
    typeof entry.mine === "boolean"
  );
};

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((entry) => typeof entry === "string");

/** Which side of the log an action on a message already said comes from. */
const sideOf = (arrival: Arrival) => (arrival.mine ? "mine" : "theirs");

/**
 * Whether an answer is to the ask this device made: it names that request, and
 * came from a confirmed device of this account's that the ask went to.
 */
const answersAsk = async (
  requestId: string,
  { device }: Arrival,
  { own }: Batch
): Promise<boolean> => {
  const ask = await historyAsk.get();
  return (
    typeof ask === "object" &&
    ask.requestId === requestId &&
    device !== undefined &&
    (ask.asked ?? []).includes(device) &&
    own.some((entry) => entry.id === device)
  );
};

const optional = <T>(value: unknown, is: (value: unknown) => value is T): T | undefined =>
  is(value) ? value : undefined;
const isString = (value: unknown): value is string => typeof value === "string";
const isNumber = (value: unknown): value is number => typeof value === "number";

/**
 * One entry of a group's thread, relayed by the member who wrote it.
 *
 * A member sends only what they said, so every entry is theirs: it is filed
 * under the session's account, and one naming anybody else is dropped. Their
 * receipts and the reactions on it are their own record and stay with them;
 * edits and removals are part of the message and come with it.
 */
const relayed = (entry: StoredMessage, author: number): StoredMessage | null => {
  if (entry.author !== undefined && entry.author !== author) return null;
  const replyTo = optional(entry.replyTo, isString);
  const editedAt = optional(entry.editedAt, isString);
  const rev = optional(entry.rev, isNumber);
  const removedAt = optional(entry.removedAt, isString);
  return {
    id: entry.id,
    at: entry.at,
    body: entry.body,
    mine: false,
    author,
    ...(replyTo !== undefined ? { replyTo } : {}),
    ...(editedAt !== undefined ? { editedAt } : {}),
    ...(rev !== undefined ? { rev } : {}),
    ...(removedAt !== undefined ? { removedAt } : {}),
  };
};

export const KINDS = {
  text: kind({
    parse: (raw: Raw) =>
      typeof raw.id === "string" && typeof raw.body === "string"
        ? {
            id: raw.id,
            at: typeof raw.at === "string" ? raw.at : "",
            body: raw.body,
            // A reply to a message this device never had is still a message:
            // the quote is dropped, the words are not.
            ...(typeof raw.replyTo === "string" ? { replyTo: raw.replyTo } : {}),
          }
        : null,
    from: "any",
    handle: async (envelope, { conversationId, createdAt, mine, author }, batch) => {
      await messageLog.append(conversationId, {
        id: envelope.id,
        ...(envelope.replyTo ? { replyTo: envelope.replyTo } : {}),
        // The sender's own clock, so every copy of one message is dated alike
        // rather than by when each device happened to collect it.
        at: envelope.at || createdAt,
        body: envelope.body,
        // A message that arrived on one of this account's own sessions is the
        // sender's own outbox catching up, and belongs on the sender's side.
        mine,
        // Who said it, so an edit or a removal can be held to the person whose
        // message it is rather than to the side it came from.
        ...(author !== undefined ? { author } : {}),
      });
      // Only theirs is worth reporting: this account already knows when it sent
      // its own, and a receipt addressed at yourself tells nobody anything.
      if (!mine)
        batch.landed.set(conversationId, [
          ...(batch.landed.get(conversationId) ?? []),
          envelope.id,
        ]);
      return conversationId;
    },
  }),

  // Not a message: news about ones already sent. A receipt that moved nothing
  // leaves the thread alone.
  receipt: kind<{ state: ReceiptState; ids: string[] }>({
    parse: ({ state, ids }: Raw) =>
      (state === "delivered" || state === "read") && isStringArray(ids) ? { state, ids } : null,
    from: "any",
    handle: async ({ ids, state }, { conversationId }) =>
      (await messageLog.markReceipts(conversationId, ids, state)) ? conversationId : undefined,
  }),

  // Acting on a message already said. On a roster the side it arrived on is not
  // enough, because an edit or a removal is a claim about a message's author and
  // "somebody else" is several people, so the session's account goes with it
  // and the log refuses one that does not match the author it is acting on.
  reaction: kind({
    parse: (raw: Raw) =>
      typeof raw.targetId === "string" &&
      typeof raw.emoji === "string" &&
      typeof raw.on === "boolean"
        ? { targetId: raw.targetId, emoji: raw.emoji, on: raw.on }
        : null,
    from: "any",
    handle: async ({ targetId, emoji, on }, arrival) =>
      (await messageLog.applyReaction(arrival.conversationId, targetId, emoji, on, sideOf(arrival)))
        ? arrival.conversationId
        : undefined,
  }),

  edit: kind({
    parse: (raw: Raw) =>
      typeof raw.targetId === "string" &&
      typeof raw.body === "string" &&
      typeof raw.rev === "number"
        ? {
            targetId: raw.targetId,
            at: typeof raw.at === "string" ? raw.at : "",
            body: raw.body,
            rev: raw.rev,
          }
        : null,
    from: "any",
    handle: async ({ targetId, body, at, rev }, arrival) =>
      (await messageLog.applyEdit(
        arrival.conversationId,
        targetId,
        body,
        at || arrival.createdAt,
        sideOf(arrival),
        rev,
        arrival.author
      ))
        ? arrival.conversationId
        : undefined,
  }),

  remove: kind({
    parse: (raw: Raw) => (typeof raw.targetId === "string" ? { targetId: raw.targetId } : null),
    from: "any",
    handle: async ({ targetId }, arrival) =>
      (await messageLog.applyRemove(
        arrival.conversationId,
        targetId,
        sideOf(arrival),
        arrival.createdAt,
        arrival.author
      ))
        ? arrival.conversationId
        : undefined,
  }),

  // Between this account's own devices only. A device that has just been
  // registered holds no history and cannot derive any: it asks, and a device
  // that already has it answers if the person holding it agrees.
  "history-request": kind({
    parse: (raw: Raw) =>
      typeof raw.requestId === "string" &&
      typeof raw.deviceId === "string" &&
      typeof raw.fingerprint === "string"
        ? { requestId: raw.requestId, deviceId: raw.deviceId, fingerprint: raw.fingerprint }
        : null,
    from: "self",
    // Written down to be served, or declined, after the queue is drained, as
    // the person answered when they confirmed the device. Only from a
    // confirmed device, by its own directory entry.
    handle: async (envelope, _arrival, { own }) => {
      const device = own.find((entry) => entry.id === envelope.deviceId);
      if (!device || device.fingerprintKey !== envelope.fingerprint) return undefined;
      await pendingHistoryRequest.set({
        requestId: envelope.requestId,
        deviceId: device.id,
        fingerprint: device.fingerprintKey,
        at: new Date().toISOString(),
      });
      return undefined;
    },
  }),

  history: kind({
    parse: (raw: Raw) =>
      typeof raw.requestId === "string" &&
      typeof raw.seq === "number" &&
      typeof raw.conversationId === "string" &&
      Array.isArray(raw.messages)
        ? {
            requestId: raw.requestId,
            seq: raw.seq,
            last: raw.last === true,
            conversationId: raw.conversationId,
            // Each entry is checked before it is believed: one without the
            // fields a thread is read by would be filed under `undefined`,
            // where the next like it looks like the same message.
            messages: raw.messages.filter(isStoredMessage),
          }
        : null,
    from: "self",
    // Taken only as the answer to the question this device asked.
    handle: async (envelope, arrival, batch) => {
      if (!(await answersAsk(envelope.requestId, arrival, batch))) return undefined;
      const added = await messageLog.merge(envelope.conversationId, envelope.messages);
      if (envelope.last) await historyAsk.close();
      return added > 0 ? envelope.conversationId : undefined;
    },
  }),

  "history-declined": kind({
    parse: (raw: Raw) => (typeof raw.requestId === "string" ? { requestId: raw.requestId } : null),
    from: "self",
    // Answered, and the answer was no. Asking again is a person's decision
    // rather than something to retry into.
    handle: async ({ requestId }, arrival, batch) => {
      if (await answersAsk(requestId, arrival, batch)) await historyAsk.close();
      return undefined;
    },
  }),

  // Between the people on one group, inside the conversation it is about:
  // somebody who has just joined asking for what was said before they did, and
  // the answer. Never on this account's own sessions, which have their own kind
  // of transfer above.
  "thread-history-request": kind({
    parse: (raw: Raw) => (typeof raw.requestId === "string" ? { requestId: raw.requestId } : null),
    from: "other",
    // Served after the queue is drained, so a transfer does not hold up the
    // rest of the collection. Without a session author there is nobody to
    // answer: the session was opened before this device recorded who is behind
    // one.
    handle: async ({ requestId }, { conversationId, author }, batch) => {
      if (author !== undefined) batch.asking.push({ conversationId, requestId, userId: author });
      return undefined;
    },
  }),

  "thread-history": kind({
    parse: (raw: Raw) =>
      typeof raw.requestId === "string" &&
      typeof raw.seq === "number" &&
      Array.isArray(raw.messages)
        ? {
            requestId: raw.requestId,
            seq: raw.seq,
            last: raw.last === true,
            messages: raw.messages.filter(isStoredMessage),
          }
        : null,
    from: "other",
    // Taken only as the answer to the ask this device made, and only from a
    // session that says whose it is.
    handle: async (envelope, { conversationId, author }) => {
      const ask = await threadCatchUp.get(conversationId);
      if (author === undefined || ask?.requestId !== envelope.requestId) return undefined;
      const said = envelope.messages
        .map((message) => relayed(message, author))
        .filter((message): message is StoredMessage => message !== null);
      const added = await messageLog.merge(conversationId, said);
      if (envelope.last) await threadCatchUp.answered(conversationId, author);
      return added > 0 ? conversationId : undefined;
    },
  }),
};

type EnvelopeKind = keyof typeof KINDS;

export type Envelope = {
  [K in EnvelopeKind]: { v: 1; kind: K } & ((typeof KINDS)[K] extends KindSpec<infer F>
    ? F
    : never);
}[EnvelopeKind];

/** Every kind this version understands, so it can tell a later one from a broken one. */
const KNOWN_KINDS: ReadonlySet<string> = new Set(Object.keys(KINDS));

/** A name for one message, known to both sides and to nobody else. */
export const newMessageId = (): string => crypto.randomUUID();

/**
 * Read what came out of the ratchet, whatever shape it is in.
 *
 * Every field a kind needs is checked before the envelope is believed. Half of
 * one is not a message with something missing -- it is an id this log would
 * file under `undefined`, where the next one like it looks like the same
 * message and is dropped as a duplicate. Anything that does not check out is
 * read as the plain body it may always have been, under the queue row's own id,
 * which is unique per item and cannot collide.
 */
export function unpack(plaintext: string, fallbackId: string): Envelope | null {
  const asBody: Envelope = { v: 1, kind: "text", id: fallbackId, at: "", body: plaintext };
  let parsed: Raw;
  try {
    parsed = JSON.parse(plaintext) as Raw;
  } catch {
    return asBody;
  }
  if (parsed?.v !== 1 || typeof parsed.kind !== "string") return asBody;
  // A kind this version does not know is from a later one, and is not for it to
  // guess at: printing the protocol into somebody's thread is the one outcome
  // worse than ignoring it. A kind it *does* know, arriving half-written, is a
  // different thing and still reads as the words it may always have been.
  if (!KNOWN_KINDS.has(parsed.kind)) return null;
  const name = parsed.kind as EnvelopeKind;
  const spec: KindSpec<object> = KINDS[name];
  const fields = spec.parse(parsed);
  return fields === null ? asBody : ({ ...fields, v: 1, kind: name } as Envelope);
}

/** The most one queued message may hold: `MAX_PAYLOAD_BYTES` on the server. */
const MAX_PAYLOAD_BYTES = 64 * 1024;

/** Room kept in each part for the envelope around its messages and the ratchet's framing. */
const PART_OVERHEAD_BYTES = 1024;

/**
 * One thread cut into parts that each fit in one queued message, newest part
 * first and each part in the thread's own order.
 *
 * Cut by size rather than by count: forty short messages and forty long ones
 * are very different sizes, and a part the server refuses stops the transfer
 * at that part every time it is tried. A message too large to travel on its own
 * is left out, so the rest of the thread still goes.
 */
function parts(messages: StoredMessage[]): StoredMessage[][] {
  const room = MAX_PAYLOAD_BYTES - PART_OVERHEAD_BYTES;
  const encoder = new TextEncoder();
  const cut: StoredMessage[][] = [];
  let part: StoredMessage[] = [];
  let size = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    // The comma between two entries counts as well.
    const bytes = encoder.encode(JSON.stringify(messages[index])).length + 1;
    if (bytes > room) continue;
    if (size + bytes > room) {
      cut.push(part.reverse());
      part = [];
      size = 0;
    }
    part.push(messages[index]);
    size += bytes;
  }
  if (part.length > 0) cut.push(part.reverse());
  return cut;
}

/**
 * Hand threads over in numbered parts, closed by an empty last one.
 *
 * Newest first within each thread, so a transfer that stops leaves the oldest
 * behind rather than a random half. Numbering carries on from `seq`, so a
 * transfer that stopped can pick up where it was; `finished` hears about each
 * thread once all of it has gone. Answers whether the whole transfer went out,
 * stopping at the first part that does not.
 */
export async function sendTransfer(
  conversationIds: string[],
  seq: number,
  send: (part: {
    conversationId: string;
    messages: StoredMessage[];
    seq: number;
    last: boolean;
  }) => Promise<boolean>,
  finished?: (conversationId: string) => Promise<void>
): Promise<boolean> {
  let next = seq;
  for (const conversationId of conversationIds) {
    for (const part of parts(await messageLog.get(conversationId))) {
      next += 1;
      if (!(await send({ conversationId, messages: part, seq: next, last: false }))) return false;
    }
    await finished?.(conversationId);
  }
  const closing = { conversationId: conversationIds[0] ?? "", messages: [], seq: next + 1 };
  return send({ ...closing, last: true });
}

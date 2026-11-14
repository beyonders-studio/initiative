import type { TFunction } from "i18next";

/** A `t` holding the `intake` namespace, whatever else it holds. */
export type TicketTitleT = TFunction<any>;

/** Where each stream's topic names are, as a filer reads them. */
const TOPIC_KEYS: Record<string, string> = {
  support: "intake:help.topics",
  security: "intake:security.topics",
  moderation: "intake:moderationTopics",
};

/**
 * What a filed ticket is called to its filer: what they called it; else what
 * it is about, for a ticket filed without a subject (feedback, an appeal);
 * else its stream.
 */
export const ticketTitle = (
  t: TicketTitleT,
  ticket: { subject?: string | null; stream: string; topic?: string | null }
): string => {
  if (ticket.subject) return ticket.subject;
  const stream: string = t(`intake:streams.${ticket.stream}.title`);
  const base = TOPIC_KEYS[ticket.stream];
  if (!ticket.topic || !base) return stream;
  return t(`${base}.${ticket.topic}`, { defaultValue: stream });
};

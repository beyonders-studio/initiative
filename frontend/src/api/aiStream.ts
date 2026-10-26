import { type AxiosRequestConfig, isAxiosError } from "axios";

import type { AIStreamEvent } from "@/api/generated/initiativeAPI.schemas";

/** A generated request for an answer streamed as JSON lines, given the
 *  options that read it as it arrives. */
export type AIStreamRequest = (
  options: AxiosRequestConfig,
  signal: AbortSignal
) => Promise<unknown>;

/**
 * Send ``request`` and hand each line of the answer to ``onEvent`` as it is
 * written. A refusal throws as any request's would, with its body read as
 * JSON, so {@link getErrorMessage} finds its code.
 */
export const readAIStream = async (
  request: AIStreamRequest,
  signal: AbortSignal,
  onEvent: (event: AIStreamEvent) => void
): Promise<void> => {
  let read = 0;
  let pending = "";
  // The answer so far, of which the lines not yet handed on are read.
  const take = (answer: string, ended: boolean) => {
    pending += answer.slice(read);
    read = answer.length;
    const lines = pending.split("\n");
    pending = ended ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as AIStreamEvent);
    }
  };
  let answer: unknown;
  try {
    answer = await request(
      {
        responseType: "text",
        // The browser's request holds the answer as far as it has arrived.
        onDownloadProgress: ({ event }) => {
          const sent = (event?.target as XMLHttpRequest | undefined)?.responseText;
          if (sent) take(sent, false);
        },
      },
      signal
    );
  } catch (error) {
    if (isAxiosError(error) && typeof error.response?.data === "string") {
      try {
        error.response.data = JSON.parse(error.response.data);
      } catch {
        // Not a JSON body: the message falls back to the caller's own.
      }
    }
    throw error;
  }
  take(String(answer ?? ""), true);
};

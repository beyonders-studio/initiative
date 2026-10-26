import type { AxiosRequestConfig } from "axios";

import type { AIStreamEvent } from "@/api/generated/initiativeAPI.schemas";

/** A generated request for an answer streamed as JSON lines, given the
 *  options that read it as it arrives. */
export type AIStreamRequest = (
  options: AxiosRequestConfig,
  signal: AbortSignal
) => Promise<unknown>;

const succeeded = (status: number | undefined) =>
  status !== undefined && status >= 200 && status < 300;

/**
 * Send ``request`` and hand each line of the answer to ``onEvent`` as it is
 * written. A refusal reads as any request's would: its body is JSON by the
 * time the shared interceptors see it, so a sign-in step it asks for opens,
 * and {@link getErrorMessage} finds its code.
 */
export const readAIStream = async (
  request: AIStreamRequest,
  signal: AbortSignal,
  onEvent: (event: AIStreamEvent) => void
): Promise<void> => {
  // A retried request, after a session renewal say, is read from its start.
  let attempt: XMLHttpRequest | undefined;
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
  const answer = await request(
    {
      responseType: "text",
      transformResponse: (data: unknown, _headers, status) => {
        if (succeeded(status) || typeof data !== "string") return data;
        try {
          return JSON.parse(data);
        } catch {
          return data;
        }
      },
      // The browser's request holds the answer as far as it has arrived.
      onDownloadProgress: ({ event }) => {
        const xhr = event?.target as XMLHttpRequest | undefined;
        if (!xhr || !succeeded(xhr.status)) return;
        if (xhr !== attempt) {
          attempt = xhr;
          read = 0;
          pending = "";
        }
        take(xhr.responseText, false);
      },
    },
    signal
  );
  take(String(answer ?? ""), true);
};

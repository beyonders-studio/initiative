import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { getErrorCode, getErrorMessage } from "./errorMessage";

/** An AxiosError carrying the body the API actually returns. */
function apiError(status: number, data: unknown): AxiosError {
  const error = new AxiosError("request failed", "ERR_BAD_REQUEST");
  error.response = {
    status,
    statusText: "",
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
}

/** The shape FastAPI's 422 handler emits — a list, not a code. */
function validation422(msg: string, field = "title") {
  return apiError(422, {
    detail: [{ type: "value_error", loc: ["body", field], msg }],
  });
}

describe("getErrorMessage", () => {
  it("localizes a flat code raised by a schema validator", () => {
    const message = getErrorMessage(validation422("Value error, RESERVED_SIGIL_IN_NAME"));
    expect(message).toBe("Names and titles can’t contain # or @.");
  });

  it("localizes a flat code from a string detail", () => {
    const message = getErrorMessage(apiError(400, { detail: "RESERVED_SIGIL_IN_NAME" }));
    expect(message).toBe("Names and titles can’t contain # or @.");
  });

  it("falls back rather than showing pydantic's own wording", () => {
    const message = getErrorMessage(
      validation422("String should have at most 255 characters"),
      "errors:fallback"
    );
    expect(message).not.toContain("String should have");
  });

  it("never returns a non-string for a list-shaped detail", () => {
    expect(typeof getErrorMessage(validation422("Value error, NOT_A_KNOWN_CODE"))).toBe("string");
  });

  it("names the kind a shared refusal is about", () => {
    expect(getErrorMessage(apiError(404, { detail: "NOT_FOUND", params: { kind: "file" } }))).toBe(
      "File not found"
    );
    expect(
      getErrorMessage(apiError(403, { detail: "NO_ACCESS", params: { kind: "calendar_event" } }))
    ).toBe("You don't have access to this event");
  });

  it("names the fields a person left empty, built-ins in the reader's words", () => {
    expect(
      getErrorMessage(
        apiError(400, { detail: "REQUIRED_FIELDS_MISSING", params: { fields: "dates\nSize" } })
      )
    ).toBe("Fill in what is required first: Start and due dates and Size.");
  });

  it("keeps an unknown string detail verbatim", () => {
    expect(getErrorMessage(apiError(400, { detail: "Something specific" }))).toBe(
      "Something specific"
    );
  });
});

describe("getErrorCode", () => {
  it("reads the code out of a 422 list", () => {
    expect(getErrorCode(validation422("Value error, RESERVED_SIGIL_IN_NAME"))).toBe(
      "RESERVED_SIGIL_IN_NAME"
    );
  });

  it("is null when a 422 carries no flat code", () => {
    expect(getErrorCode(validation422("Field required"))).toBeNull();
  });

  it("reads a plain string detail", () => {
    expect(getErrorCode(apiError(403, { detail: "FORBIDDEN" }))).toBe("FORBIDDEN");
  });
});

describe("a 429", () => {
  it("reads the app's own refusal rather than calling it a rate limit", () => {
    expect(getErrorMessage(apiError(429, { detail: "QUERY_BUSY" }))).toBe(
      "This community already has as many queries running as it may. Try again in a moment."
    );
  });

  it("still says rate limited when the limiter answered without a code", () => {
    expect(getErrorMessage(apiError(429, { error: "1 per 1 minute" }))).toBe(
      "Too many requests. Please wait a moment and try again."
    );
  });
});

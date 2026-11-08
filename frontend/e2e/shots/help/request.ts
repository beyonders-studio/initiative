import { expect, type Page } from "@playwright/test";

/**
 * Call the API as the person signed in on `page`, from the page itself, the
 * way the app does: a write from anywhere else is refused for not saying where
 * it came from. The page must already be on the app. Returns the status and
 * the body's text.
 */
export async function send(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const response = await fetch(`/api/v1${path}`, {
        method,
        credentials: "include",
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return { status: response.status, text: await response.text() };
    },
    { method, path, body }
  );
}

/** {@link send}, failing on an error, and returning the parsed body. */
export async function api<T = unknown>(
  page: Page,
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const { status, text } = await send(page, method, path, body);
  expect(status, `${method} ${path}: ${text}`).toBeLessThan(300);
  return (text ? JSON.parse(text) : null) as T;
}

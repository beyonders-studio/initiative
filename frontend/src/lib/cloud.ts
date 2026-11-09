/**
 * Initiative Cloud, the hosted service. Its address is the CLOUD_ORIGIN file
 * at the project root, which the build bakes in and the backend reads.
 */
export const CLOUD_ORIGIN = __CLOUD_ORIGIN__;
export const CLOUD_SERVER_URL = `${CLOUD_ORIGIN}/api/v1`;

/**
 * Whether a server's origin is Initiative Cloud's. The Vite dev server counts
 * as Cloud, as its backend does with DEV_AS_CLOUD, so what only Cloud offers
 * can be tried locally; a built app or a test run never does.
 */
export const isCloudOrigin = (origin: string | null): boolean =>
  origin === CLOUD_ORIGIN || import.meta.env.MODE === "development";

/**
 * Whether Initiative Cloud is open. Until it is, the apps offer it as coming
 * soon and a fresh install starts with no server; once it is, the apps start
 * on it and offer it beside your own server.
 */
export const CLOUD_OPEN = false;

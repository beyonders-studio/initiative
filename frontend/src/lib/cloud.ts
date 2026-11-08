/**
 * Initiative Cloud, the hosted service. Its address is the CLOUD_ORIGIN file
 * at the project root, which the build bakes in and the backend reads.
 */
export const CLOUD_ORIGIN = __CLOUD_ORIGIN__;
export const CLOUD_SERVER_URL = `${CLOUD_ORIGIN}/api/v1`;

/**
 * Whether Initiative Cloud is open. Until it is, the apps offer it as coming
 * soon and a fresh install starts with no server; once it is, the apps start
 * on it and offer it beside your own server.
 */
export const CLOUD_OPEN = false;

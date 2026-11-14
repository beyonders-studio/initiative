/**
 * Whether an app update was published by this project.
 *
 * A release image carries a statement of the bundle it serves (its version,
 * the sha256 of the zip, the oldest app it runs on) signed with the project's
 * release key. The app installs only a bundle whose statement verifies against
 * a key it was built with; the updater then checks the zip against the
 * statement's digest.
 */

/** ECDSA P-256 public keys (SPKI, base64). The first signs releases; the second
 *  is kept offline to replace it. A dev build adds the dev key's with
 *  `VITE_OTA_DEV_PUBLIC_KEY`. */
const RELEASE_KEYS: readonly string[] = [
  "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEmC5sqg4Q71BRwU4fGluJvOizFTkqlZRMfEP2Wj6f24BRBBEIEqu6058/eAw2/UGnP/03qha23WE5n7DpvQFh1Q==",
  "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEwIWhh/MTBmKSRiCzS8LcyTWEoqYhv4Qz0OFq7+oMRAzg8XYkLaGq/XVbF0Bap1s+YFaGe0QN9Nasox8KmlbOhQ==",
  ...(import.meta.env.VITE_OTA_DEV_PUBLIC_KEY
    ? [import.meta.env.VITE_OTA_DEV_PUBLIC_KEY as string]
    : []),
];

export interface UpdateStatement {
  v: 1;
  version: string;
  /** sha256 hex of the bundle zip. */
  sha256: string;
  /** The oldest native app (APK/IPA) the bundle runs on. */
  minNativeVersion: string;
  /** The oldest desktop app it runs on. */
  minDesktopVersion: string;
}

const fromBase64 = (value: string) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));

/** The statement, when `signature` is one of `keys` over its exact bytes. */
export const verifiedStatement = async (
  statement: string,
  signature: string,
  keys: readonly string[] = RELEASE_KEYS
): Promise<UpdateStatement | null> => {
  const data = new TextEncoder().encode(statement);
  for (const spki of keys) {
    try {
      const key = await crypto.subtle.importKey(
        "spki",
        fromBase64(spki),
        { name: "ECDSA", namedCurve: "P-256" },
        false,
        ["verify"]
      );
      if (
        await crypto.subtle.verify(
          { name: "ECDSA", hash: "SHA-256" },
          key,
          fromBase64(signature),
          data
        )
      ) {
        const parsed = JSON.parse(statement) as UpdateStatement;
        return parsed.v === 1 ? parsed : null;
      }
    } catch {
      // A key or signature that does not decode verifies nothing.
    }
  }
  return null;
};

/**
 * Which devices this browser will encrypt to and read from. Every directory --
 * another person's, and this account's own -- is read through `ingestDirectory`,
 * and what it returns is the only thing the session openers take.
 */

import { readDirectory } from "@/api/generated/direct-messages/direct-messages";
import type { DmSessionKey } from "@/api/generated/initiativeAPI.schemas";

import { ratchet } from "./client";
import {
  deviceId,
  deviceOwner,
  type PeerKeyChange,
  peerDeviceKeys,
  peerKeyChanges,
  sessionForDevice,
} from "./store";

declare const trusted: unique symbol;

/**
 * A device that has been through `ingestDirectory`, which is the only place one
 * is made: its keys verified against its own signature.
 */
export interface TrustedDevice {
  readonly id: string;
  readonly userId: number;
  readonly identityKey: string;
  readonly fingerprintKey: string;
  /** Set on this account's own devices, which the device list describes. */
  readonly label?: string | null;
  readonly createdAt?: string;
  readonly [trusted]: true;
}

/** One device as a directory lists it: a person's, or one of this account's own. */
export type DirectoryEntry = Pick<
  DmSessionKey,
  "device_id" | "identity_key" | "fingerprint_key" | "signature"
> & { label?: string | null; created_at?: string };

/**
 * One account's devices that may be addressed, and, for this account's own,
 * the ones held until the person has verified them.
 */
export interface PeerDirectory {
  devices: TrustedDevice[];
  held: TrustedDevice[];
  /** The directory could not be read, which is not the same as it being empty. */
  unavailable?: boolean;
}

async function trust(userId: number, entry: DirectoryEntry): Promise<TrustedDevice | null> {
  const verifies = await ratchet
    .verifyDevice(userId, entry.identity_key, entry.fingerprint_key, entry.signature)
    .catch(() => false);
  if (!verifies) return null;
  return {
    id: entry.device_id,
    userId,
    identityKey: entry.identity_key,
    fingerprintKey: entry.fingerprint_key,
    ...(entry.label !== undefined ? { label: entry.label } : {}),
    ...(entry.created_at !== undefined ? { createdAt: entry.created_at } : {}),
  } as TrustedDevice;
}

/**
 * Check one account's listed devices, and notice any that changed.
 *
 * A device whose signature does not verify is left out, as is one that signs
 * nothing; neither is a change for anybody to confirm.
 * What remains is compared against the keys this browser has seen for that
 * account before. A changed or newly introduced device of this account's own
 * is held until the person verifies it from here, so nothing is encrypted to it
 * until then. Another person's is noted, for the conversation to mention, and
 * addressed as listed.
 *
 * This account's own devices come through here too. Their baseline is seeded
 * by the first read without holding anything, so the devices an account already
 * had are not asked about; one that appears after that is.
 */
export async function ingestDirectory(
  userId: number,
  entries: DirectoryEntry[],
  { listedSince }: { listedSince?: number } = {}
): Promise<PeerDirectory> {
  const own = userId === (await deviceOwner.get());
  const listed = (await Promise.all(entries.map((entry) => trust(userId, entry)))).filter(
    (device): device is TrustedDevice => device !== null
  );
  const changes = await peerDeviceKeys.reconcile(
    userId,
    await Promise.all(
      listed.map(async (device) => ({
        deviceId: device.id,
        fingerprint: device.fingerprintKey,
        identityKey: device.identityKey,
        label: device.label,
        // A session already open with one of their devices says this browser
        // has been talking to them, so a first read is not a first sighting.
        // This account's own sessions say nothing about its baseline.
        previouslyAddressed: !own && (await sessionForDevice.get(device.id)) !== undefined,
      }))
    ),
    { hold: own }
  );
  // This browser's own device is recorded in the baseline like the rest, and
  // is the one device nobody needs to confirm.
  const here = own ? await deviceId.get() : undefined;
  if (changes.some((change) => change.deviceId === here)) {
    await peerKeyChanges.acknowledge([here as string]);
  }
  // `reconcile` wrote the holds in the transaction that recorded the keys.
  // The session in hand was negotiated with the key that has just been
  // replaced, so its pointer is dropped and the next send opens a fresh one
  // against the key the directory now returns.
  await Promise.all(changes.map((change) => sessionForDevice.forget(change.deviceId)));
  if (!own) return { devices: listed, held: [] };

  // A device that has left the account since it was held is no longer a
  // question. Read against everything listed, not only what verified: a
  // device whose signature fails is still there, just not addressable.
  if (listedSince !== undefined) {
    await peerKeyChanges.withdrawUnlisted(
      userId,
      entries.map((entry) => entry.device_id),
      listedSince
    );
  }

  // Held on every read until acknowledged, not only the one that noticed it.
  const held = new Set(
    (await peerKeyChanges.all())
      .filter((change) => change.userId === userId)
      .map((change) => change.deviceId)
  );
  return {
    devices: listed.filter((device) => !held.has(device.id)),
    held: listed.filter((device) => held.has(device.id)),
  };
}

/** Read another person's directory through the seam. */
export async function readPeerDirectory(userId: number): Promise<PeerDirectory> {
  return ingestDirectory(userId, (await readDirectory(userId)).devices);
}

/** Newest first: if several have accrued, the latest is the one being reacted to. */
const newestFirst = (changes: PeerKeyChange[]) =>
  [...changes].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

/** A device of this account's that appeared after this browser's baseline, to be verified. */
export async function ownDeviceWaiting(): Promise<PeerKeyChange | null> {
  const owner = await deviceOwner.get();
  const own = (await peerKeyChanges.all()).filter((change) => change.userId === owner);
  return newestFirst(own)[0] ?? null;
}

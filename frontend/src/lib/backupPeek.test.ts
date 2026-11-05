import { strToU8, zipSync } from "fflate";
import { describe, expect, it, vi } from "vitest";

import { peekBackupManifest } from "./backupPeek";

const MARK = 0xffffffff;

/** Little-endian fields, each `[bytes, value]`. */
const le = (...fields: Array<[2 | 4 | 8, number]>) => {
  const view = new DataView(new ArrayBuffer(fields.reduce((n, [size]) => n + size, 0)));
  let at = 0;
  for (const [size, value] of fields) {
    if (size === 2) view.setUint16(at, value, true);
    else if (size === 4) view.setUint32(at, value, true);
    else view.setBigUint64(at, BigInt(value), true);
    at += size;
  }
  return new Uint8Array(view.buffer);
};

const length = (parts: Uint8Array[]) => parts.reduce((n, part) => n + part.length, 0);

/** A backup holding only its manifest, stored, with every figure kept the
 *  zip64 way, as in a backup past 4 GB. */
const zip64Backup = (manifest: object) => {
  const name = new TextEncoder().encode("manifest.json");
  const data = new TextEncoder().encode(JSON.stringify(manifest));
  const sizes: Array<[8, number]> = [
    [8, data.length],
    [8, data.length],
  ];
  const local = [
    le([4, 0x04034b50], [2, 45], [2, 0], [2, 0], [4, 0], [4, 0], [4, MARK], [4, MARK]),
    le([2, name.length], [2, 20]),
    name,
    le([2, 1], [2, 16], ...sizes),
    data,
  ];
  const central = [
    le([4, 0x02014b50], [2, 45], [2, 45], [2, 0], [2, 0], [4, 0], [4, 0], [4, MARK]),
    le([4, MARK], [2, name.length], [2, 28], [2, 0], [2, 0], [2, 0], [4, 0], [4, MARK]),
    name,
    le([2, 1], [2, 24], ...sizes, [8, 0]),
  ];
  const centralAt = length(local);
  const recordAt = centralAt + length(central);
  const end = [
    le([4, 0x06064b50], [8, 44], [2, 45], [2, 45], [4, 0], [4, 0], [8, 1], [8, 1]),
    le([8, length(central)], [8, centralAt]),
    le([4, 0x07064b50], [4, 0], [8, recordAt], [4, 1]),
    le([4, 0x06054b50], [2, 0], [2, 0], [2, 0xffff], [2, 0xffff], [4, MARK], [4, MARK], [2, 0]),
  ];
  return new File([...local, ...central, ...end], "backup.zip");
};

describe("peekBackupManifest", () => {
  it("reads the manifest of an ordinary backup", async () => {
    const manifest = { type: "guild-backup", guild: { name: "The Fete" } };
    const zipped = zipSync(
      {
        "assets/raffle.png": new Uint8Array(64),
        "manifest.json": strToU8(JSON.stringify(manifest)),
      },
      { level: 0 }
    );

    await expect(peekBackupManifest(new File([zipped], "backup.zip"))).resolves.toEqual(manifest);
  });

  it("reads the manifest of a backup kept the zip64 way", async () => {
    const manifest = { type: "initiative-backup", guild: { name: "The Fete" } };

    await expect(peekBackupManifest(zip64Backup(manifest))).resolves.toEqual(manifest);
  });

  it("reads a directory a piece at a time, however large it says it is", async () => {
    const claimed = 3 * 1024 * 1024;
    const file = new File(
      [
        new Uint8Array(claimed),
        le([4, 0x06054b50], [2, 0], [2, 0], [2, 1], [2, 1], [4, claimed], [4, 0], [2, 0]),
      ],
      "backup.zip"
    );
    const slice = vi.spyOn(file, "slice");

    await expect(peekBackupManifest(file)).rejects.toMatchObject({ code: "not_backup" });
    const read = slice.mock.calls.map(([start = 0, end = file.size]) => end - start);
    expect(Math.max(...read)).toBeLessThanOrEqual(1024 * 1024);
  });
});

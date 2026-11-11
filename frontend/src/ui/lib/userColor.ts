// Matches Excalidraw's internal getClientColor() — a djb2-style hash of a
// string feeding into hsl(hue, 100%, 83%) via `(hash % 37) * 10`. See
// @excalidraw/excalidraw/dist/dev/index.js → clients.ts. Excalidraw exposes
// no hook to override the cursor color, so we feed it an id string that
// hashes to the bucket we want, and mirror the same formula here for the
// avatar badge.
//
// Small decimal user ids ("1", "2", …) cluster badly in djb2 — every char
// is in [48, 57], so near ids all land in a tight hue band. Spread the id
// through Knuth's multiplicative hash first so consecutive user ids produce
// well-separated hues. A plug-in's reference to a person is spread already,
// and is hashed as it is.

const KNUTH = 2654435761;

const spreadUserId = (userId: number | string): string =>
  typeof userId === "number" ? String((Math.abs(userId) * KNUTH) >>> 0) : userId;

const djb2 = (id: string): number => {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash << 5) - hash + id.charCodeAt(i);
  }
  return hash;
};

export const getUserColorHsl = (userId: number | string): string => {
  const hash = Math.abs(djb2(spreadUserId(userId)));
  const hue = (hash % 37) * 10;
  return `hsl(${hue}, 100%, 83%)`;
};

// Foreground/background pair spreadable into a React ``style`` prop. Every
// bucket produced by ``getUserColorHsl`` is a bright pastel at lightness
// 83%, so a single dark text color is readable on all of them — there's no
// need for a theme-aware or per-hue foreground. Slate-900 matches what
// ``CollaboratorAvatar`` already hard-coded against these backgrounds.
export const getUserColorStyle = (userId: number | string) => ({
  backgroundColor: getUserColorHsl(userId),
  color: "#0f172a",
});

// The string to pass as Collaborator.id so Excalidraw's getClientColor()
// lands on the same hue as getUserColorHsl(userId).
export const userColorHashId = (userId: number): string => spreadUserId(userId);

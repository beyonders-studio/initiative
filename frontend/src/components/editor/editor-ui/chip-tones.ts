import { SmartChipTone } from "@/api/generated/initiativeAPI.schemas";

/**
 * The classes a tone renders in.
 *
 * The server decides the tone because what counts as finished or late is a
 * product rule; this decides only what that looks like. A chip whose thing
 * carries its own colour ignores all of it.
 *
 * Every colour here is a theme token, so a chip follows the reader's theme the
 * way the rest of the app does rather than carrying a fixed palette with a
 * dark-mode patch bolted on.
 */
export const CHIP_TONE_CLASSES: Record<SmartChipTone, string> = {
  [SmartChipTone.neutral]: "bg-muted text-muted-foreground",
  [SmartChipTone.muted]: "bg-muted/60 text-muted-foreground/80",
  [SmartChipTone.good]: "bg-success/15 text-success",
  [SmartChipTone.warn]: "bg-warning/15 text-warning",
  [SmartChipTone.danger]: "bg-destructive/15 text-destructive",
};

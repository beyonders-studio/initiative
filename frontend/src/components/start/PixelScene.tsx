/**
 * Small pixel-art pictures for the start flow, drawn in the same chunky style
 * as Yonder and the completion effects. Each scene is a 16x12 grid; every
 * character names a colour in the scene's palette.
 */

import { cellsFromLayout, type PixelLayout } from "@/components/effects/svg/pixelLayout";
import type { StartPath } from "@/lib/startFlow";
import { cn } from "@/ui/lib/utils";

interface Scene {
  layout: PixelLayout;
  palette: Record<string, string>;
}

/** Yonder's outline brown, shared so the scenes sit beside him. */
const OUTLINE = "#2A1A0A";

/** An envelope sealed with a heart. */
const INVITE: Scene = {
  layout: [
    "                ",
    " kkkkkkkkkkkkkk ",
    " kkwwwwwwwwwwkk ",
    " kwkwwwwwwwwkwk ",
    " kwwkwwwwwwkwwk ",
    " kwwwkwwwwkwwwk ",
    " kwwwwkrrkwwwwk ",
    " kwwwwrrrrwwwwk ",
    " kwwwwwrrwwwwwk ",
    " kwwwwwwwwwwwwk ",
    " kkkkkkkkkkkkkk ",
    "                ",
  ],
  palette: { k: OUTLINE, w: "#FFF7E8", r: "#EF4444" },
};

/** A clubhouse with a pennant on the roof. */
const JOIN: Scene = {
  layout: [
    "       kyyy     ",
    "       kyy      ",
    "       k        ",
    "      kRk       ",
    "     kRRRk      ",
    "    kRRRRRk     ",
    "   kRRRRRRRk    ",
    "  kRRRRRRRRRk   ",
    "   kwwwwwwwk    ",
    "   kwbwwwbwk    ",
    "   kwwdddwwk    ",
    "   kkkdddkkk    ",
  ],
  palette: {
    k: OUTLINE,
    y: "#FACC15",
    R: "#3B82F6",
    w: "#FDE7C7",
    b: "#7DD3FC",
    d: "#8B5E3C",
  },
};

/** A checklist, two things done and one to go. */
const PERSONAL: Scene = {
  layout: [
    "      kGGk      ",
    "  kkkkGGGGkkkk  ",
    "  kwwwwwwwwwwk  ",
    "  kwggwlllllwk  ",
    "  kwggwwwwwwwk  ",
    "  kwwwwwwwwwwk  ",
    "  kwggwllllwwk  ",
    "  kwggwwwwwwwk  ",
    "  kwwwwwwwwwwk  ",
    "  kwoowlllllwk  ",
    "  kwoowwwwwwwk  ",
    "  kkkkkkkkkkkk  ",
  ],
  palette: {
    k: OUTLINE,
    G: "#9CA3AF",
    w: "#FFFFFF",
    g: "#22C55E",
    l: "#CBD5E1",
    o: "#E2E8F0",
  },
};

/** Three people and a sparkle over the one in the middle. */
const SHARED: Scene = {
  layout: [
    "       yy       ",
    "                ",
    "       nn       ",
    "       hh       ",
    "  nn  RRRR  nn  ",
    "  hh  RRRR  hh  ",
    " bbbb RRRR eeee ",
    " bbbb  dd  eeee ",
    " bbbb  dd  eeee ",
    "  dd        dd  ",
    "  dd        dd  ",
    "                ",
  ],
  palette: {
    y: "#FACC15",
    n: "#5C3A1E",
    h: "#F2C29B",
    R: "#A855F7",
    b: "#3B82F6",
    e: "#10B981",
    d: "#334155",
  },
};

export const PATH_SCENES: Record<StartPath, Scene> = {
  invite: INVITE,
  join: JOIN,
  personal: PERSONAL,
  shared: SHARED,
};

/** The tile each path's scene sits on. */
export const PATH_TINTS: Record<StartPath, string> = {
  invite: "bg-amber-400/20",
  join: "bg-sky-400/20",
  personal: "bg-emerald-400/20",
  shared: "bg-violet-400/20",
};

export const PixelScene = ({ scene, className }: { scene: Scene; className?: string }) => (
  <svg
    viewBox="0 0 16 12"
    xmlns="http://www.w3.org/2000/svg"
    className={cn("h-auto w-12", className)}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges" }}
    aria-hidden="true"
    focusable="false"
  >
    {cellsFromLayout(scene.layout).map(({ x, y, char }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={scene.palette[char]} />
    ))}
  </svg>
);

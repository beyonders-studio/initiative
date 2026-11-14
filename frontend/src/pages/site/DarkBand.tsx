/**
 * The navy band the front door's big sections sit on: the sign-in pages' hex
 * backdrop with the aurora over it, and stars if the section wants them. It
 * stays dark in either theme; the light sections around it are what follow
 * the theme.
 */

import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/ui/lib/utils";

import { Starfield } from "./effects";

/** The aurora's dark variant, which a navy band wants whatever the theme. */
const AURORA = [
  "radial-gradient(ellipse 100% 60% at 50% -10%, oklch(0.5 0.25 280 / 0.45), transparent)",
  "radial-gradient(ellipse 80% 50% at 80% 110%, oklch(0.45 0.2 220 / 0.4), transparent)",
  "radial-gradient(ellipse 60% 40% at 10% 60%, oklch(0.4 0.18 300 / 0.35), transparent)",
].join(", ");

export const DarkBand = ({
  stars = false,
  className,
  children,
  ...rest
}: { stars?: boolean; children: ReactNode } & ComponentPropsWithoutRef<"section">) => (
  <section
    className={cn("relative isolate overflow-hidden bg-[#0b1224] text-white", className)}
    {...rest}
  >
    <div
      aria-hidden="true"
      className="absolute inset-0 -z-10 bg-center opacity-50"
      style={{ backgroundImage: "url(/images/hexWhite.svg)", backgroundSize: "67px 116px" }}
    />
    <div
      aria-hidden="true"
      className="aurora-bg absolute inset-0 -z-10"
      style={{ backgroundImage: AURORA }}
    />
    {stars ? <Starfield isDark /> : null}
    {children}
  </section>
);

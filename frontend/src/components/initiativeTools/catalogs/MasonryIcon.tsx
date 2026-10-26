import type { LucideProps } from "lucide-react";
import { forwardRef } from "react";

/**
 * A masonry wall, drawn to match Lucide's grid icons: two columns of
 * unequal blocks. Lucide has no such icon of its own.
 */
export const MasonryIcon = forwardRef<SVGSVGElement, LucideProps>(
  ({ size = 24, strokeWidth = 2, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
      {...props}
    >
      <rect x="3" y="3" width="8" height="11" rx="1" />
      <rect x="3" y="17" width="8" height="4" rx="1" />
      <rect x="13" y="3" width="8" height="5" rx="1" />
      <rect x="13" y="11" width="8" height="10" rx="1" />
    </svg>
  )
);
MasonryIcon.displayName = "MasonryIcon";

import { type SVGProps, useId } from "react";

import { usePride } from "@/hooks/usePride";
import { cn } from "@/ui/lib/utils";

type LogoIconProps = SVGProps<SVGSVGElement>;

// Pride flag colours, in order, used to paint the mark when Pride mode is on.
const PRIDE_COLORS = [
  "#e40303", // red
  "#ff8c00", // orange
  "#ffed00", // yellow
  "#008026", // green
  "#004dff", // blue
  "#750787", // violet
];

export const LogoIcon = ({ className, ...props }: LogoIconProps) => {
  const { enabled: pride } = usePride();
  // useId() embeds colons that break `url(#…)` references in some engines.
  const gradientId = `pride-logo-${useId().replace(/:/g, "")}`;
  const fill = pride ? `url(#${gradientId})` : "currentColor";

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      xmlSpace="preserve"
      style={{
        fillRule: "evenodd",
        clipRule: "evenodd",
        strokeLinejoin: "round",
        strokeMiterlimit: 2,
      }}
      viewBox="0 0 438 471"
      className={cn("text-primary", pride && "pride-logo", className)}
      {...props}
    >
      {pride ? (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            {PRIDE_COLORS.map((color, index) => (
              <stop
                key={color}
                offset={`${(index / (PRIDE_COLORS.length - 1)) * 100}%`}
                stopColor={color}
              />
            ))}
          </linearGradient>
        </defs>
      ) : null}
      <path
        d="M218.82 470.128a20.242 20.242 0 0 1-8.27-1.639L14.387 384.823C5.724 381.128 0 371.834 0 361.464v-238.72c0-.652.023-1.3.067-1.943.298-4.21 1.546-8.282 3.62-11.81 1.54-2.615 3.524-4.918 5.884-6.758a21.969 21.969 0 0 1 2.994-1.966l196.161-97.74C211.98.753 215.431-.054 218.82.002c3.39-.057 6.84.751 10.094 2.523l196.161 97.741a21.969 21.969 0 0 1 2.994 1.966c2.36 1.84 4.345 4.143 5.885 6.757 2.073 3.53 3.321 7.601 3.62 11.811.043.643.066 1.291.066 1.942v238.721c0 10.37-5.724 19.664-14.388 23.36l-196.16 83.665a20.242 20.242 0 0 1-8.272 1.64ZM137.623 188.27a24.668 24.668 0 0 1-22.62 1.39l-70.298-31.046v185.628l120.247 51.288V243.097a53.369 53.369 0 0 1 27.81-46.853 53.367 53.367 0 0 1 52.116 0l.5.28a53.369 53.369 0 0 1 27.31 46.573V395.53l120.247-51.288V158.613l-70.648 31.25a24.67 24.67 0 0 1-22.634-1.383l-.186-.112a24.669 24.669 0 0 1 2.616-43.713l56.324-25.09L218.82 52.643 79.233 119.565l55.934 24.884a24.668 24.668 0 0 1 2.626 43.718l-.17.102Z"
        fill={fill}
      />
      <ellipse
        cx="257.233"
        cy="209.745"
        rx="52.118"
        ry="36.171"
        transform="matrix(.76806 0 0 1.13407 21.073 -109.942)"
        fill={fill}
      />
      <path
        d="m137.623 188.27.17-.103a24.669 24.669 0 0 0-2.626-43.718l-55.934-24.884L218.82 52.643l139.587 66.922-56.324 25.09a24.67 24.67 0 0 0-2.616 43.713l.186.112a24.67 24.67 0 0 0 22.634 1.383l70.648-31.25v185.628L272.688 395.53V243.097a53.369 53.369 0 0 0-27.31-46.574l-.5-.279a53.367 53.367 0 0 0-52.116 0l-.5.28a53.369 53.369 0 0 0-27.31 46.573V395.53L44.705 344.241V158.613l70.298 31.045a24.668 24.668 0 0 0 22.62-1.389Zm81.02-101.366c-22.093 0-40.03 18.381-40.03 41.021s17.937 41.021 40.03 41.021c22.092 0 40.028-18.38 40.028-41.02 0-22.64-17.936-41.022-40.029-41.022Z"
        opacity=".25"
        fill={fill}
      />
    </svg>
  );
};

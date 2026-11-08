import {
  type CSSProperties,
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { getItem, setItem } from "@/lib/storage";

/**
 * An event the app dresses up for while it runs. Its wordmark and primary
 * buttons are dressed by styles.css under `html[data-event-theme="<id>"]`; the
 * logo by `logoColors` and `logoDecoration` here.
 */
export interface EventTheme {
  id: "pride" | "christmas" | "newYear";
  /** Whether the event is running on this (local) date. */
  isOn: (date: Date) => boolean;
  /** Paints the mark as a gradient of these, in order, each colour once. */
  logoColors?: string[];
  /** Drawn over the mark, in the logo's 438×471 view box. */
  logoDecoration?: (date: Date) => ReactNode;
}

/** Snowflakes over the logo: across, size, seconds to fall, start offset, and
 *  where each rests when motion is reduced. */
const SNOWFLAKES = [
  { x: 60, r: 20, fall: 5.2, delay: -0.4, rest: 180 },
  { x: 100, r: 12, fall: 3.8, delay: -1.2, rest: 400 },
  { x: 130, r: 14, fall: 4.1, delay: -2.9, rest: 300 },
  { x: 200, r: 24, fall: 6.3, delay: -1.7, rest: 240 },
  { x: 270, r: 16, fall: 4.6, delay: -3.8, rest: 360 },
  { x: 310, r: 12, fall: 4.9, delay: -4.4, rest: 120 },
  { x: 340, r: 22, fall: 5.6, delay: -0.9, rest: 200 },
  { x: 400, r: 14, fall: 4.3, delay: -2.2, rest: 330 },
];

/** Four-pointed sparkles around the logo: centre, reach, start offset. */
const SPARKLES = [
  { x: 52, y: 52, s: 36, delay: 0 },
  { x: 392, y: 40, s: 28, delay: -0.9 },
  { x: 410, y: 250, s: 24, delay: -1.6 },
  { x: 26, y: 262, s: 22, delay: -0.5 },
];

const sparklePath = ({ x, y, s }: { x: number; y: number; s: number }) =>
  `M${x} ${y - s}Q${x} ${y} ${x + s} ${y}Q${x} ${y} ${x} ${y + s}Q${x} ${y} ${x - s} ${y}Q${x} ${y} ${x} ${y - s}Z`;

export const EVENT_THEMES: EventTheme[] = [
  {
    // Pride Month: the rainbow, flowing everywhere.
    id: "pride",
    isOn: (date) => date.getMonth() === 5,
    logoColors: ["#e40303", "#ff8c00", "#ffed00", "#008026", "#004dff", "#750787"],
  },
  {
    // December, up to Boxing Day.
    id: "christmas",
    isOn: (date) => date.getMonth() === 11 && date.getDate() <= 25,
    // Snow falling over the mark, and settled along its roof.
    logoDecoration: () => (
      <g fill="#fff" stroke="#cfe3f2">
        {SNOWFLAKES.map(({ x, r, fall, delay, rest }) => (
          <circle
            key={x}
            className="event-snowflake"
            cx={x}
            cy="0"
            r={r}
            strokeWidth="4"
            style={
              {
                animationDuration: `${fall}s`,
                animationDelay: `${delay}s`,
                "--rest": `${rest}px`,
              } as CSSProperties
            }
          />
        ))}
        <path
          d="M6 106 L218.8 0 L432 106 L430 128 L392 110 Q384 132 372 104 L312 76 Q304 100 290 68 L232 40 Q219 64 206 40 L148 68 Q134 100 126 76 L66 104 Q54 132 46 110 L8 128 Z"
          strokeWidth="6"
          strokeLinejoin="round"
        />
      </g>
    ),
  },
  {
    // Boxing Day until 2 January.
    id: "newYear",
    isOn: (date) =>
      (date.getMonth() === 11 && date.getDate() >= 26) ||
      (date.getMonth() === 0 && date.getDate() === 1),
    // The year being rung in on a gold plaque, with sparkles twinkling round it.
    logoDecoration: (date) => (
      <g>
        {SPARKLES.map((sparkle) => (
          <path
            key={sparkle.x}
            className="event-sparkle"
            d={sparklePath(sparkle)}
            fill="#f5c542"
            style={{ animationDelay: `${sparkle.delay}s` }}
          />
        ))}
        <rect
          x="34"
          y="318"
          width="370"
          height="146"
          rx="56"
          fill="#e2b13c"
          style={{ stroke: "var(--background)" }}
          strokeWidth="16"
        />
        <text
          x="219"
          y="391"
          textAnchor="middle"
          dominantBaseline="central"
          fontSize="124"
          fontWeight="800"
          fill="#3a2a00"
        >
          {date.getFullYear() + (date.getMonth() === 11 ? 1 : 0)}
        </text>
      </g>
    ),
  },
];

interface EventThemeContextValue {
  /** Whether this device lets the app dress up for events (Event themes). */
  allowed: boolean;
  /** The event showing now: allowed, and one is running. */
  active: EventTheme | null;
  setAllowed: (allowed: boolean) => void;
}

const EventThemeContext = createContext<EventThemeContextValue | undefined>(undefined);

const EVENT_THEMES_STORAGE_KEY = "initiative-event-themes";

const applyEventTheme = (event: EventTheme | null) => {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  if (event) {
    root.dataset.eventTheme = event.id;
  } else {
    delete root.dataset.eventTheme;
  }
};

export const EventThemeProvider = ({ children }: { children: React.ReactNode }) => {
  const [allowed, setAllowedState] = useState(() => getItem(EVENT_THEMES_STORAGE_KEY) !== "off");
  // Read on mount and when the switch moves; an event that starts or ends while
  // the app stays open is settled by the next reload.
  const active = useMemo(() => {
    const today = new Date();
    return allowed ? (EVENT_THEMES.find((event) => event.isOn(today)) ?? null) : null;
  }, [allowed]);

  useEffect(() => {
    applyEventTheme(active);
  }, [active]);

  const setAllowed = useCallback((next: boolean) => {
    setAllowedState(next);
    setItem(EVENT_THEMES_STORAGE_KEY, next ? "on" : "off");
  }, []);

  const value = useMemo(() => ({ allowed, active, setAllowed }), [allowed, active, setAllowed]);

  return <EventThemeContext.Provider value={value}>{children}</EventThemeContext.Provider>;
};

/**
 * Read the event theme. Falls back to none when no provider is mounted so the
 * (widely embedded, purely cosmetic) `LogoIcon` never crashes an isolated
 * render or test — unlike the throw-on-missing convention of the data hooks.
 */
export const useEventTheme = (): EventThemeContextValue => {
  return (
    useContext(EventThemeContext) ?? {
      allowed: true,
      active: null,
      setAllowed: () => {},
    }
  );
};

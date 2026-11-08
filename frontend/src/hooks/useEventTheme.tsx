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
 * An event the app dresses up for while it runs. Its colours, if it has any,
 * paint the logo, the wordmark and the primary buttons' borders as a flowing
 * gradient; its decoration, if it has one, is drawn over the logo.
 */
export interface EventTheme {
  id: "pride" | "christmas" | "newYear";
  /** Whether the event is running on this (local) date. */
  isOn: (date: Date) => boolean;
  /** Gradient stops, in order, each colour once. */
  colors?: string[];
  /** Drawn over the mark, in the logo's 438×471 view box. `fill` is the logo's
   *  own paint. */
  logoDecoration?: (props: { date: Date; fill: string }) => ReactNode;
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

export const EVENT_THEMES: EventTheme[] = [
  {
    // Pride Month.
    id: "pride",
    isOn: (date) => date.getMonth() === 5,
    colors: ["#e40303", "#ff8c00", "#ffed00", "#008026", "#004dff", "#750787"],
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
    // The year being rung in, on a banner across the foot of the mark.
    logoDecoration: ({ date, fill }) => (
      <g>
        <rect
          x="34"
          y="318"
          width="370"
          height="146"
          rx="56"
          fill={fill}
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
          fill="#fff"
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
  if (event?.colors) {
    root.dataset.eventGradient = "";
    // The first stop again at the end, so the flowing gradient wraps seamlessly.
    root.style.setProperty(
      "--event-gradient",
      `linear-gradient(90deg, ${[...event.colors, event.colors[0]].join(", ")})`
    );
  } else {
    delete root.dataset.eventGradient;
    root.style.removeProperty("--event-gradient");
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

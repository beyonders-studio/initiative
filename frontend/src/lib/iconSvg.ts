/**
 * A lucide icon as an SVG string, for the places that cannot render React.
 *
 * A canvas is one of those: it draws images, not components. The alternatives
 * were `react-dom/server`, which is 200KB of renderer to turn a fifteen-icon set
 * into markup, and a second table mapping each kind to its icon's path data —
 * the same thing written twice, and the two would drift.
 *
 * So this reads the icon node, which is lucide's own description of an icon: a list
 * of `[tag, attributes]` that its components draw from. Taking the data and
 * drawing it here means the icon in the picture is the icon in the list, from
 * one source, and it costs nothing. The component itself is never called — it
 * reads a context, and a component with a hook in it cannot be rendered by hand.
 */

import type { ComponentType } from "react";

/** What lucide wraps every icon's own shapes in. */
const SVG_ATTRS = [
  'xmlns="http://www.w3.org/2000/svg"',
  'width="24"',
  'height="24"',
  'viewBox="0 0 24 24"',
  'fill="none"',
  'stroke-linecap="round"',
  'stroke-linejoin="round"',
].join(" ");

/** Attributes SVG spells in camelCase. Everything else is kebab-cased. */
const CAMEL_ATTRS = new Set(["viewBox", "preserveAspectRatio", "baseProfile"]);

const attrName = (name: string) => {
  if (name === "className") return "class";
  if (CAMEL_ATTRS.has(name)) return name;
  return name.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
};

const escapeAttr = (value: string) =>
  value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/** One shape, as lucide describes it. */
type IconNodeChild = [string, Record<string, string | number>];

const shape = ([tag, attrs]: IconNodeChild): string => {
  const rendered = Object.entries(attrs ?? {})
    // `key` is React's, not SVG's.
    .filter(([name, value]) => name !== "key" && value != null)
    .map(([name, value]) => `${attrName(name)}="${escapeAttr(String(value))}"`)
    .join(" ");
  return `<${tag}${rendered ? ` ${rendered}` : ""} />`;
};

/** Lucide's description of an icon, read off the element it makes. */
const iconNodeOf = (Icon: ComponentType<unknown>): IconNodeChild[] | null => {
  const forwarded = Icon as unknown as {
    render?: (
      props: object,
      ref: null
    ) => { props?: { iconNode?: unknown; icon?: { node?: unknown } } } | null;
  };
  if (typeof forwarded.render !== "function") return null;
  // Making the element is not rendering it: this one call reaches no hook.
  const props = forwarded.render({}, null)?.props;
  // lucide 1.58 passes `icon: { node }`; earlier releases passed `iconNode`.
  const node = props?.icon?.node ?? props?.iconNode;
  return Array.isArray(node) ? (node as IconNodeChild[]) : null;
};

/**
 * The icon's markup, or null when it is not a lucide icon.
 *
 * Null rather than a throw: a node that cannot draw its mark is a node drawn
 * without one, which is a far better outcome than a picture that does not draw.
 */
export const iconSvg = (
  Icon: ComponentType<{ color?: string; strokeWidth?: number }>,
  colour: string,
  strokeWidth = 2.5
): string | null => {
  const iconNode = iconNodeOf(Icon as ComponentType<unknown>);
  if (!iconNode || iconNode.length === 0) return null;
  const body = iconNode.map(shape).join("");
  return `<svg ${SVG_ATTRS} stroke="${escapeAttr(colour)}" stroke-width="${strokeWidth}">${body}</svg>`;
};

/** The same icon as something an `<img>` or a canvas can load. */
export const iconDataUri = (
  Icon: ComponentType<{ color?: string; strokeWidth?: number }>,
  colour: string
): string | null => {
  const markup = iconSvg(Icon, colour);
  if (!markup) return null;
  // `encodeURIComponent` rather than base64: the markup is ASCII, and this
  // keeps it readable in the dev tools.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
};

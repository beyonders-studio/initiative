// Pixel position of the text caret inside a <textarea> or a one-line
// <input>, relative to the
// element's top-left (border box). Used to anchor the mention popover under
// the word being typed rather than under the whole field.
//
// Standard "mirror div" technique: render a hidden div that copies the
// textarea's box + text styles, fill it with the text up to `position`, then
// measure a marker span placed at the caret.

// Style properties that affect text layout and must be mirrored for the
// measurement to line up with the real textarea.
const MIRRORED_PROPERTIES = [
  "direction",
  "boxSizing",
  "width",
  "height",
  "overflowX",
  "overflowY",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "borderStyle",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontStyle",
  "fontVariant",
  "fontWeight",
  "fontStretch",
  "fontSize",
  "lineHeight",
  "fontFamily",
  "textAlign",
  "textTransform",
  "textIndent",
  "letterSpacing",
  "wordSpacing",
  "tabSize",
] as const;

export interface CaretCoordinates {
  /** Distance from the textarea's top border to the top of the caret line. */
  top: number;
  /** Distance from the textarea's left border to the caret. */
  left: number;
  /** The caret line's height, so callers can offset below it. */
  height: number;
}

export function getCaretCoordinates(
  element: HTMLTextAreaElement | HTMLInputElement,
  position: number
): CaretCoordinates {
  const computed = window.getComputedStyle(element);

  const div = document.createElement("div");
  const style = div.style as unknown as Record<string, string>;
  const computedRecord = computed as unknown as Record<string, string>;

  style.position = "absolute";
  style.visibility = "hidden";
  // A one-line field never wraps; it scrolls, which `scrollLeft` below undoes.
  style.whiteSpace = element instanceof HTMLInputElement ? "pre" : "pre-wrap";
  style.wordWrap = "break-word";
  style.overflow = "hidden";
  for (const prop of MIRRORED_PROPERTIES) {
    style[prop] = computedRecord[prop];
  }

  document.body.appendChild(div);
  try {
    div.textContent = element.value.slice(0, position);

    const span = document.createElement("span");
    // A non-empty node so it has measurable box metrics even at the very end.
    span.textContent = element.value.slice(position) || ".";
    div.appendChild(span);

    return {
      top: span.offsetTop + parseInt(computed.borderTopWidth || "0", 10) - element.scrollTop,
      left: span.offsetLeft + parseInt(computed.borderLeftWidth || "0", 10) - element.scrollLeft,
      height: parseInt(computed.lineHeight || "0", 10) || element.clientHeight,
    };
  } finally {
    document.body.removeChild(div);
  }
}

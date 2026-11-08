export const truncateText = (value: string, limit = 50): string => {
  if (!value) {
    return "";
  }
  const trimmed = value.trim();
  if (trimmed.length <= limit) {
    return trimmed;
  }
  return `${trimmed.slice(0, limit).trimEnd()}…`;
};

/**
 * A number box where blank means none: `value` is `null` for blank text and
 * the number typed otherwise, and `valid` says the text is blank or a whole
 * number from `min` to `max`.
 */
export const readOptionalWholeNumber = (
  text: string,
  min: number,
  max: number = Number.MAX_SAFE_INTEGER
): { value: number | null; valid: boolean } => {
  const trimmed = text.trim();
  const value = trimmed === "" ? null : Number(trimmed);
  return {
    value,
    valid: value === null || (Number.isInteger(value) && value >= min && value <= max),
  };
};

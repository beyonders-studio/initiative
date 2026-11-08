import { useParams } from "@tanstack/react-router";

/**
 * The id the address names in its `name` param, such as a detail page's
 * `projectId`. Null when the address names none, or names something that is
 * not a positive whole number; a detail hook holds its request for null.
 */
export function useRouteId(name: `${string}Id`): number | null {
  const params = useParams({ strict: false }) as Record<string, string | undefined>;
  const id = Number(params[name]);
  return Number.isInteger(id) && id > 0 ? id : null;
}

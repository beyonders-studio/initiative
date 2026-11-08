import { useListHomeLayouts } from "@/api/generated/home-layouts/home-layouts";

/** The home layouts the marketplace offers, all at once: one shelf. */
export const useHomeLayoutListings = (options?: { enabled?: boolean }) =>
  useListHomeLayouts({
    query: {
      staleTime: 5 * 60_000,
      enabled: options?.enabled ?? true,
      select: (data) => data.items,
    },
  });

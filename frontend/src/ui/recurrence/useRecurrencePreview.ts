import { keepPreviousData, skipToken, useQuery } from "@tanstack/react-query";

import type { RecurrencePreviewRequest } from "@/api/generated/initiativeAPI.schemas";
import { host } from "@/ui/host";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/**
 * A repeat's next starts, from the engine the calendar uses, asked once the
 * form stops changing. `null` asks nothing, and so does a host that previews
 * no repeats. A rule the server refuses shows no dates rather than an error:
 * the form says what is wrong with it. `settled` is false while the form has
 * changed since the dates were asked.
 */
export const useRecurrencePreview = (request: RecurrencePreviewRequest | null) => {
  // Debounced as a string: a request object is new on every render.
  const latest = request ? JSON.stringify(request) : null;
  const key = useDebouncedValue(latest, 300);
  const preview = host.previewRecurrence;
  const query = useQuery({
    queryKey: ["recurrence-preview", key],
    queryFn:
      key !== null && preview
        ? () => preview(JSON.parse(key) as RecurrencePreviewRequest)
        : skipToken,
    placeholderData: keepPreviousData,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  return { ...query, settled: key === latest };
};

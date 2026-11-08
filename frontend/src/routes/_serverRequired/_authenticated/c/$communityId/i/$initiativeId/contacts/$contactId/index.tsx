import { createFileRoute } from "@tanstack/react-router";

import { getReadContactQueryOptions } from "@/api/generated/contacts/contacts";
import { commentThreadQueryOptions } from "@/hooks/useComments";
import { ContactDetailPage } from "@/pages/initiativeTools/contacts/ContactDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/contacts/$contactId/"
)({
  loader: ({ context, params }) => {
    const contactId = Number(params.contactId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it; the page fetches
    // for itself and reports a failure.
    void Promise.all([
      queryClient.ensureQueryData(getReadContactQueryOptions(communityId, contactId)),
      queryClient.ensureInfiniteQueryData({
        ...commentThreadQueryOptions(communityId, { contact_id: contactId }),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: ContactDetailPage,
});

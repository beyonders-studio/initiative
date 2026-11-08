import { moveContact } from "@/api/generated/contacts/contacts";
import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const contacts = TOOL_HOOKS[Tool.contact];

export const useContactsList = contacts.useList;
export const useContact = contacts.useDetail;
export const useCreateContact = contacts.useCreate;
export const useUpdateContact = contacts.useUpdate;
export const useDeleteContact = contacts.useDelete;
export const useSetContactGrants = contacts.useSetGrants;

/**
 * Move an initiative's contact into the community's contacts. It leaves the
 * initiative's lists and joins the community's, so every contact list goes.
 */
export const useMoveContact = (id: number, options?: MutationOpts<ContactRead, void>) =>
  useCommunityMutation<ContactRead, void>(
    {
      mutationFn: (communityId) => moveContact(communityId, id),
      invalidate: () => invalidate(q.tool(Tool.contact, id), q.relationships()),
      errorKey: "contacts:error",
    },
    options
  );

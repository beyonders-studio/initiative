/**
 * The owner's intake settings: which community receives operations work,
 * which project each stream lands in, and who somebody is told to contact.
 *
 * Every hook here is behind `config.manage` on the server. The read carries
 * every stream whether bound or not, so the page renders the full set rather
 * than only what somebody already configured.
 */

import type {
  FeedbackSwitchUpdate,
  IntakeBindingRead,
  IntakeBindingUpsert,
  IntakeContactUpdate,
  IntakeOptionsRead,
  IntakeSettingsRead,
  IntakeStream,
  OperationsCommunityUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  deleteBinding,
  importBlueprint,
  updateFeedbackSwitch,
  updateGeneralContact,
  updateOperationsCommunity,
  updateStreamContact,
  upsertBinding,
  useReadIntakeOptions,
  useReadIntakeSettings,
} from "@/api/generated/intake/intake";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Where each stream lands, and when it last opened a case. */
export const useIntakeSettings = (options?: QueryOpts<IntakeSettingsRead>) =>
  useReadIntakeSettings({ query: options });

/** The operations community's initiatives, projects and statuses, for the pickers. */
export const useIntakeOptions = (options?: QueryOpts<IntakeOptionsRead>) =>
  useReadIntakeOptions({ query: options });

/**
 * Both reads are invalidated by every write: naming a community changes what
 * the pickers can offer, and binding a stream changes what the list shows.
 */
const refreshIntake = () =>
  invalidate(q.intakeSettings(), q.intakeOptions(), q.ticketAvailability());

export const useUpdateOperationsCommunity = (
  options?: MutationOpts<IntakeSettingsRead, OperationsCommunityUpdate>
) =>
  useApiMutation<IntakeSettingsRead, OperationsCommunityUpdate>(
    {
      mutationFn: (data) => updateOperationsCommunity(data),
      invalidate: refreshIntake,
    },
    options
  );

export const useUpsertIntakeBinding = (
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; body: IntakeBindingUpsert }>(
    {
      mutationFn: ({ stream, body }) => upsertBinding(stream, body),
      invalidate: refreshIntake,
    },
    options
  );

export const useImportIntakeBlueprint = (
  options?: MutationOpts<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>
) =>
  useApiMutation<IntakeBindingRead, { stream: IntakeStream; initiativeId: number }>(
    {
      mutationFn: ({ stream, initiativeId }) =>
        importBlueprint(stream, {
          initiative_id: initiativeId,
        }),
      invalidate: refreshIntake,
    },
    options
  );

export const useDeleteIntakeBinding = (options?: MutationOpts<void, IntakeStream>) =>
  useApiMutation<void, IntakeStream>(
    {
      mutationFn: (stream) => deleteBinding(stream),
      invalidate: refreshIntake,
    },
    options
  );

/** The deployment's catch-all contact address; `null` clears it. */
/** Let people here send feedback to the Initiative team, or stop. */
export const useUpdateFeedbackSwitch = (
  options?: MutationOpts<IntakeSettingsRead, FeedbackSwitchUpdate>
) =>
  useApiMutation<IntakeSettingsRead, FeedbackSwitchUpdate>(
    {
      mutationFn: (data) => updateFeedbackSwitch(data),
      invalidate: refreshIntake,
    },
    options
  );

export const useUpdateIntakeGeneralContact = (
  options?: MutationOpts<IntakeSettingsRead, IntakeContactUpdate>
) =>
  useApiMutation<IntakeSettingsRead, IntakeContactUpdate>(
    {
      mutationFn: (data) => updateGeneralContact(data),
      invalidate: refreshIntake,
    },
    options
  );

/** One stream's own contact address; `null` clears it back to the general one. */
export const useUpdateIntakeStreamContact = (
  options?: MutationOpts<IntakeSettingsRead, { stream: IntakeStream; body: IntakeContactUpdate }>
) =>
  useApiMutation<IntakeSettingsRead, { stream: IntakeStream; body: IntakeContactUpdate }>(
    {
      mutationFn: ({ stream, body }) => updateStreamContact(stream, body),
      invalidate: refreshIntake,
    },
    options
  );

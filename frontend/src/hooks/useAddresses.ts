import type {
  HeldChangeRead,
  UserEmailListResponse,
  UserEmailRead,
  VerificationSendResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  addMyAddress,
  getListMyAddressesQueryKey,
  makeMyAddressPrimary,
  removeMyAddress,
  useListMyAddresses,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const ADDRESSES_QUERY_KEY = getListMyAddressesQueryKey();

const refresh = () => queryClient.invalidateQueries({ queryKey: ADDRESSES_QUERY_KEY });

// ── Queries ─────────────────────────────────────────────────────────────────

/** Every address this account holds, proven or not. */
export const useMyAddresses = () => useListMyAddresses();

// ── Mutations ───────────────────────────────────────────────────────────────

/**
 * Every change to the list is confirmed with the current password, where the
 * list says one is asked for; `null` otherwise, and a recent sign-in answers.
 */
type Confirmed = { currentPassword: string | null };
export type AddressAdd = Confirmed & { email: string };
export type AddressChange = Confirmed & { addressId: number };

/**
 * Start holding another address.
 *
 * The answer is the same whoever holds it already — a claim is recorded and
 * mail goes out, or nothing happens and mail goes to whoever proved it. So
 * there is one success message and it describes the letter, not the outcome.
 */
export const useAddAddress = (options?: MutationOpts<VerificationSendResponse, AddressAdd>) =>
  useApiMutation<VerificationSendResponse, AddressAdd>(
    {
      mutationFn: ({ email, currentPassword }) =>
        addMyAddress({ email, current_password: currentPassword }),
      invalidate: refresh,
    },
    options
  );

/** Removing an address answers with the change held, or `held: null` where
 * it was made at once. */
type Removed = Awaited<ReturnType<typeof removeMyAddress>>;

export const useRemoveAddress = (options?: MutationOpts<Removed, AddressChange>) =>
  useApiMutation<Removed, AddressChange>(
    {
      mutationFn: ({ addressId, currentPassword }) =>
        removeMyAddress(addressId, {
          current_password: currentPassword,
        }),
      invalidate: refresh,
    },
    options
  );

export const useMakeAddressPrimary = (
  options?: MutationOpts<UserEmailRead | HeldChangeRead, AddressChange>
) =>
  useApiMutation<UserEmailRead | HeldChangeRead, AddressChange>(
    {
      mutationFn: ({ addressId, currentPassword }) =>
        makeMyAddressPrimary(addressId, {
          current_password: currentPassword,
        }),
      invalidate: refresh,
    },
    options
  );

// ── Reading the list ────────────────────────────────────────────────────────

/**
 * Addresses minted for an account whose provider asserted none. They are
 * permanently unproven, nobody can receive mail at one, and their holder never
 * typed it — so this surface does not show them.
 */
const SYNTHETIC = "synthetic";

/** What the settings page lists: the account's own addresses, primary first. */
export const visibleAddresses = (data: UserEmailListResponse | undefined): UserEmailRead[] =>
  (data?.items ?? [])
    .filter((address) => address.source !== SYNTHETIC)
    .sort((a, b) => Number(b.is_primary) - Number(a.is_primary));

/**
 * Whether removing this address would leave the account with no proven one.
 *
 * The server refuses it either way; knowing here is what lets the button say
 * so before it is pressed rather than after.
 */
export const isOnlyProvenAddress = (address: UserEmailRead, addresses: UserEmailRead[]): boolean =>
  address.verified && addresses.filter((other) => other.verified).length === 1;

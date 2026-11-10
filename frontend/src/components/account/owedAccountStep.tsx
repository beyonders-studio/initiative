import type { ReactNode } from "react";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { AcceptTerms } from "@/components/account/AcceptTerms";
import { ChooseHandle } from "@/components/account/ChooseHandle";
import { ConfirmBirthdate } from "@/components/account/ConfirmBirthdate";

/**
 * The step an account owes before it may go anywhere, or `null`: the app's
 * shell asks it, and so does every page outside the shell that a signed-in
 * person reaches, such as a plug-in's sign-in.
 */
export const owedAccountStep = (user: UserRead | null | undefined): ReactNode => {
  // An account that was handed its handle rather than picking one chooses
  // here, before anything else: it is how everyone else will see them.
  if (user && !user.username_chosen) return <ChooseHandle />;
  // Never agreed to this deployment's terms, on a deployment that has some.
  // Signing up through the form is the agreement and is recorded there, so
  // this is the way in that had no form: an account an identity provider
  // provisioned on first sign-in.
  if (user?.legal_acceptance_required) return <AcceptTerms />;
  // No date of birth on file, on a deployment that checks age. Asked once of
  // every account — plug-ins can have a minimum age that differs by country —
  // and never again once answered. The server says when it is owed.
  if (user?.birthdate_required) return <ConfirmBirthdate />;
  return null;
};

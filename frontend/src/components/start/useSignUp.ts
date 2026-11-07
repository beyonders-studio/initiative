import { useTranslation } from "react-i18next";

import type { PasskeySignUpStart, UserRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { describePasskeyPromptError, signUpWithPasskey } from "@/lib/passkeys";

/**
 * Making an account, by password or by passkey: what the start flow's account
 * step and the first-owner page both do once the form is filled in. Each call
 * throws when the account could not be made, and `failure` says why in the
 * words the form shows.
 */
export const useSignUp = () => {
  // ``errors`` so a server code is localized without a mid-submit load.
  const { t } = useTranslation(["auth", "errors"]);
  const { register, login, applySignIn } = useAuth();

  /**
   * Registers, then signs in at once where the account is active with its
   * address verified. `signedIn` is false for one that waits on a letter or
   * an approval.
   */
  const withPassword = async (
    details: PasskeySignUpStart,
    password: string,
    inviteCode?: string
  ): Promise<{ made: UserRead; signedIn: boolean }> => {
    const made = await register({ ...details, password, inviteCode });
    const signedIn = made.status === "active" && Boolean(made.email_verified);
    if (signedIn) await login({ email: details.email, password });
    return { made, signedIn };
  };

  /**
   * Registers with a key. The ceremony that made the account signed it in, so
   * its session is adopted whole: in an app, with the refresh token it keeps.
   * Its recovery codes go to `onCodes` before anything else is awaited: they
   * are shown once, and an account with no password gets back in with them.
   */
  const withPasskey = async (
    details: PasskeySignUpStart,
    inviteCode: string | undefined,
    onCodes: (codes: string[]) => void
  ): Promise<void> => {
    const made = await signUpWithPasskey(details, inviteCode);
    onCodes(made.codes ?? []);
    await applySignIn(made);
  };

  /** What to show for a failed attempt; `passkey` for the key door. */
  const failure = (err: unknown, passkey = false): string => {
    const prompt = passkey ? describePasskeyPromptError(err) : null;
    return prompt ? t(prompt) : getErrorMessage(err, "auth:register.defaultError");
  };

  return { withPassword, withPasskey, failure };
};

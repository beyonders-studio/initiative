import { useNavigate } from "@tanstack/react-router";
import { lazy, Suspense, useState } from "react";

import { type AgeChallengeDetail, AUTH_AGE_REQUIRED_EVENT } from "@/api/client";
import { useAuthChallenge } from "@/hooks/useAuthChallenge";

// Loaded the first time the question is put, not with every page.
const AgeConfirmationDialog = lazy(() =>
  import("@/components/communities/AgeConfirmationDialog").then((m) => ({
    default: m.AgeConfirmationDialog,
  }))
);

/**
 * The age question, put by a listed community at its own door.
 *
 * Most people meet it at the directory's Join button and never again. This is
 * for the members who were never asked: somebody an identity provider's group
 * rule placed, an admin added, or who was already there when the community
 * listed itself. There was nobody at a keyboard on any of those, so the
 * question waits here until they turn up.
 *
 * Mounted once at the root, like the step-up dialogs, because the refusal can
 * come from any request a community's page makes. It is not a screen and it
 * blocks nothing else: the account keeps the rest of Initiative and every
 * private community it belongs to, and closing this returns it to where it
 * can still go.
 */
export const AgeGateDialog = () => {
  const navigate = useNavigate();
  const { challenge, clear, open } = useAuthChallenge<AgeChallengeDetail>(
    AUTH_AGE_REQUIRED_EVENT,
    (detail) => detail !== undefined
  );

  // Answering does not put them through the door on its own — the page behind
  // this was refused and is showing nothing. Sending them out to their own
  // space is somewhere real; the community they were headed for is one click
  // away now that it will let them in.
  const leave = () => {
    clear();
    void navigate({ to: "/" });
  };

  // Mounted from the first time it opens, so it closes as it opened.
  const [asked, setAsked] = useState(false);
  if (open && !asked) setAsked(true);
  if (!asked) return null;

  return (
    <Suspense fallback={null}>
      <AgeConfirmationDialog
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            leave();
          }
        }}
        onConfirmed={leave}
        answerStands={challenge?.answerStands}
      />
    </Suspense>
  );
};

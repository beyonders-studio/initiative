import { useTranslation } from "react-i18next";

import type { UserProfile } from "@/api/generated/initiativeAPI.schemas";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserHandle } from "@/components/user/UserHandle";
import {
  useAcceptMessageRequest,
  useDmPermission,
  useMessageRequests,
  useRequestMessage,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";

/**
 * Somebody you were sent here to talk to, and cannot yet.
 *
 * The new-conversation picker and a community's roster both link straight at
 * this page, which means most people they list arrive with no channel open —
 * sharing a community with somebody is not the same as their having agreed to
 * hear from you. So the destination is not an error: it is where the asking
 * happens, and the panel's whole job is to offer the one gesture that leads
 * somewhere.
 *
 * That gesture is only ever about messages. A connection is a different
 * agreement between two accounts — made by handle, answered in the requests
 * section, unmade from the actions menu — and it does not belong on a page
 * about a conversation, even though accepting one happens to open a channel as
 * well.
 *
 * Which gesture to offer comes from ``dm_permission`` and the pending list,
 * never from a guess about why. The server collapses every refusal into
 * ``denied``, so a panel built from it cannot tell the reasons apart either,
 * and the copy below does not try to.
 */
export const StartWithPerson = ({ person }: { person: UserProfile }) => {
  const { t } = useTranslation(["messages", "connections", "settings"]);

  const { data: permission } = useDmPermission(person.id);
  const { data: requests } = useMessageRequests();

  const requestMessage = useRequestMessage();
  const acceptMessage = useAcceptMessageRequest();

  const pendingIn = (list?: { user_id: number }[]) =>
    (list ?? []).some((grant) => grant.user_id === person.id);

  const waiting = pendingIn(requests?.outgoing);
  // Answered here rather than sent back to the list it also appears in: the
  // reader came looking for this one person, and it is the same answer.
  const theirs = pendingIn(requests?.incoming);
  const mayAsk = permission?.permission === "may_request";

  const body = () => {
    if (waiting) return t("messages:start.waiting");
    if (theirs) return t("messages:start.asksToMessage");
    return mayAsk ? t("messages:start.mayAsk") : t("messages:start.denied");
  };

  return (
    <div className="flex flex-1 items-center justify-center p-8 text-center">
      <div className="max-w-sm space-y-3">
        <ProfileAvatar
          user={person}
          decorations={person.profile_decorations}
          presence={person.presence}
          className="mx-auto size-16"
        />
        <UserHandle user={person} className="text-base" />
        <p className="text-muted-foreground text-sm">{body()}</p>
        {theirs ? (
          <Button
            disabled={acceptMessage.isPending}
            onClick={() => acceptMessage.mutate({ userId: person.id })}
          >
            {t("settings:privacy.requests.accept")}
          </Button>
        ) : !waiting && mayAsk ? (
          <Button
            disabled={requestMessage.isPending}
            onClick={() =>
              requestMessage.mutate(
                { data: { user_id: person.id } },
                { onSuccess: () => toast.success(t("connections:actions.askSent")) }
              )
            }
          >
            {t("connections:actions.ask")}
          </Button>
        ) : null}
      </div>
    </div>
  );
};

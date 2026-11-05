import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ContactGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { PersonRow } from "@/components/connections/PersonRow";
import { Button } from "@/components/ui/button";
import {
  useAcceptConnection,
  useAcceptMessageRequest,
  useConnections,
  useMessageRequests,
  useRemoveConnection,
  useRemoveMessageRequest,
} from "@/hooks/useDirectMessages";

type Kind = "connection" | "message";
type PendingRow = ContactGrantRead & { kind: Kind };

/**
 * Everything waiting on an answer, either way round.
 *
 * Both kinds in one list because they are the same question to the person
 * reading it — somebody wants something, say yes or no — and separating them
 * would make the reader learn a distinction the model keeps for its own
 * reasons.
 *
 * A request from an account the reader ignores never arrives here: the server
 * leaves it out, so there is nothing to filter and nothing that hints at it.
 */
export const ConnectionRequestsSection = ({
  whenEmpty,
}: {
  /** What to show with nothing waiting. A page that only offers the section
   *  when something is waiting passes ``null``. */
  whenEmpty?: ReactNode;
} = {}) => {
  const { t } = useTranslation("settings");
  const connections = useConnections();
  const messages = useMessageRequests();

  const acceptConnection = useAcceptConnection();
  const removeConnection = useRemoveConnection();
  const acceptMessage = useAcceptMessageRequest();
  const removeMessage = useRemoveMessageRequest();

  const rows: PendingRow[] = [
    ...(connections.data?.incoming ?? []).map((row) => ({ ...row, kind: "connection" as const })),
    ...(messages.data?.incoming ?? []).map((row) => ({ ...row, kind: "message" as const })),
    ...(connections.data?.outgoing ?? []).map((row) => ({ ...row, kind: "connection" as const })),
    ...(messages.data?.outgoing ?? []).map((row) => ({ ...row, kind: "message" as const })),
  ];

  const detailFor = (row: PendingRow) => {
    if (row.outgoing) {
      return row.kind === "connection"
        ? t("privacy.requests.youAskedToConnect")
        : t("privacy.requests.youAskedToMessage");
    }
    return row.kind === "connection"
      ? t("privacy.requests.wantsToConnect")
      : t("privacy.requests.askedToMessage");
  };

  const accept = (row: PendingRow) =>
    row.kind === "connection"
      ? acceptConnection.mutate({ userId: row.user_id })
      : acceptMessage.mutate({ userId: row.user_id });

  const dismiss = (row: PendingRow) =>
    row.kind === "connection"
      ? removeConnection.mutate({ userId: row.user_id })
      : removeMessage.mutate({ userId: row.user_id });

  if (rows.length === 0) {
    return whenEmpty === undefined ? (
      <p className="text-muted-foreground text-sm">{t("privacy.requests.empty")}</p>
    ) : (
      <>{whenEmpty}</>
    );
  }

  return (
    <ul className="divide-y">
      {rows.map((row) => (
        <PersonRow
          key={`${row.kind}-${row.user_id}`}
          user={{ ...row, id: row.user_id }}
          detail={detailFor(row)}
        >
          {row.outgoing ? (
            <Button variant="ghost" size="sm" onClick={() => dismiss(row)}>
              {t("privacy.requests.cancel")}
            </Button>
          ) : (
            <>
              <Button size="sm" onClick={() => accept(row)}>
                {t("privacy.requests.accept")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => dismiss(row)}>
                {t("privacy.requests.decline")}
              </Button>
            </>
          )}
        </PersonRow>
      ))}
    </ul>
  );
};

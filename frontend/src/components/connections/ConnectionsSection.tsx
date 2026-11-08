import { useTranslation } from "react-i18next";

import type { ContactGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { HandleField } from "@/components/connections/HandleField";
import { PersonRow } from "@/components/connections/PersonRow";
import {
  useConnections,
  useRemoveConnection,
  useRequestConnection,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { formatDate } from "@/ui/lib/formatDate";

interface ConnectionsSectionProps {
  /** Show the "connect by handle" field. Off where the page is a directory. */
  allowAdding?: boolean;
}

/**
 * Accepted connections, and the field that makes new ones.
 *
 * A connection is addressed by handle rather than picked from a list: that is
 * the only shape that reaches an account on Private, which is never offered
 * from a roster. Every target uses it, so there is no per-policy branch.
 */
export const ConnectionsSection = ({ allowAdding = true }: ConnectionsSectionProps) => {
  const { t } = useTranslation("settings");
  const { data } = useConnections();
  const requestConnection = useRequestConnection();
  const removeConnection = useRemoveConnection();

  const accepted: ContactGrantRead[] = data?.accepted ?? [];

  return (
    <div className="space-y-4">
      {allowAdding && (
        <HandleField
          label={t("privacy.connections.add")}
          placeholder={t("privacy.connections.addPlaceholder")}
          hint={t("privacy.connections.addHint")}
          submitLabel={t("privacy.connections.send")}
          errorFallback="errors:CONTACT_GRANT_CANNOT_REACH"
          pending={requestConnection.isPending}
          onSubmit={(handle) =>
            requestConnection
              .mutateAsync({ data: handle })
              .then(() => toast.success(t("privacy.connections.sent")))
          }
        />
      )}

      {accepted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("privacy.connections.empty")}</p>
      ) : (
        <ul className="divide-y">
          {accepted.map((connection) => (
            <PersonRow
              key={connection.user_id}
              user={{ ...connection, id: connection.user_id }}
              detail={
                connection.responded_at
                  ? t("privacy.connections.connected", {
                      date: formatDate(connection.responded_at),
                    })
                  : undefined
              }
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => removeConnection.mutate({ userId: connection.user_id })}
                disabled={removeConnection.isPending}
              >
                {t("privacy.connections.remove")}
              </Button>
            </PersonRow>
          ))}
        </ul>
      )}
    </div>
  );
};

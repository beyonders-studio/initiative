import { Plug, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AIConnectionResponse,
  AIProvider,
  ConnectionScope,
} from "@/api/generated/initiativeAPI.schemas";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { AIConnectionDialog } from "./AIConnectionDialog";
import { AIConnectionRow } from "./AIConnectionRow";
import type { ConnectionMutations } from "./aiConnection.types";

export type { ConnectionMutations } from "./aiConnection.types";

interface AIConnectionManagerProps {
  scope: ConnectionScope;
  connections: AIConnectionResponse[];
  isLoading: boolean;
  isError: boolean;
  /** Providers selectable in this scope (platform allows Ollama, community does not). */
  providers: AIProvider[];
  mutations: ConnectionMutations;
  /** AI is off where these connections serve, so none can be turned on. */
  locked?: boolean;
}

/**
 * Thin orchestrator for a list of AI connections: renders the rows, owns the
 * add/edit dialog and delete confirmation, and delegates all field/submit logic
 * to `AIConnectionDialog`. Platform and community pages reuse it via `scope`.
 */
export const AIConnectionManager = ({
  scope,
  connections,
  isLoading,
  isError,
  providers,
  mutations,
  locked = false,
}: AIConnectionManagerProps) => {
  const { t } = useTranslation("settings");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AIConnectionResponse | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AIConnectionResponse | null>(null);

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (connection: AIConnectionResponse) => {
    setEditing(connection);
    setDialogOpen(true);
  };

  const handleTest = (connection: AIConnectionResponse) => {
    mutations.test.mutate(connection.id, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success(t("ai.testSuccess"));
        } else {
          toast.error(messageForCode(data.message, "settings:ai.testError"));
        }
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:ai.testError")),
    });
  };

  const handleToggle = (connection: AIConnectionResponse, enabled: boolean) => {
    mutations.update.mutate(
      { connectionId: connection.id, data: { enabled } },
      {
        onError: (error) => toast.error(getErrorMessage(error, "settings:aiConnections.saveError")),
      }
    );
  };

  const confirmDelete = () => {
    if (!pendingDelete) return;
    mutations.remove.mutate(pendingDelete.id, {
      onSuccess: () => {
        toast.success(t("aiConnections.deleted"));
        setPendingDelete(null);
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:aiConnections.deleteError")),
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="font-medium">{t("aiConnections.title")}</h3>
          <p className="text-muted-foreground text-sm">{t(`aiConnections.subtitle_${scope}`)}</p>
          {locked && <p className="text-muted-foreground text-sm">{t("aiConnections.locked")}</p>}
        </div>
        <Button type="button" onClick={openCreate} className="shrink-0">
          <Plus className="h-4 w-4" />
          {t("aiConnections.add")}
        </Button>
      </div>

      {isLoading ? (
        <SkeletonRegion>
          <ListSkeleton rows={2} avatar={false} />
        </SkeletonRegion>
      ) : isError ? (
        <StatusMessage />
      ) : connections.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed p-6 text-center">
          <Plug className="h-6 w-6 text-muted-foreground" />
          <p className="text-muted-foreground text-sm">{t("aiConnections.empty")}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {connections.map((connection) => {
            const toggling = mutations.update.isPending ? mutations.update.variables : undefined;
            const pending =
              toggling?.connectionId === connection.id ? toggling.data.enabled : undefined;
            return (
              <AIConnectionRow
                key={connection.id}
                connection={connection}
                enabled={!locked && (pending ?? connection.enabled)}
                toggleDisabled={locked || mutations.update.isPending}
                onToggle={(enabled) => handleToggle(connection, enabled)}
                isTesting={mutations.test.isPending && mutations.test.variables === connection.id}
                testDisabled={mutations.test.isPending}
                onTest={() => handleTest(connection)}
                onEdit={() => openEdit(connection)}
                onDelete={() => setPendingDelete(connection)}
              />
            );
          })}
        </ul>
      )}

      <AIConnectionDialog
        key={editing ? `edit-${editing.id}` : "create"}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        scope={scope}
        providers={providers}
        connection={editing}
        mutations={mutations}
        onNeedsModel={openEdit}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title={t("aiConnections.deleteTitle")}
        description={t("aiConnections.deleteDescription", { label: pendingDelete?.label ?? "" })}
        confirmLabel={t("aiConnections.delete")}
        onConfirm={confirmDelete}
        isLoading={mutations.remove.isPending}
        destructive
      />
    </div>
  );
};

import { Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AIConnectionResponse } from "@/api/generated/initiativeAPI.schemas";
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";
import { messageForCode } from "@/lib/errorMessage";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { dateTimeFormat, listFormat } from "@/ui/lib/intl";
import { Switch } from "@/ui/switch";

interface AIConnectionRowProps {
  connection: AIConnectionResponse;
  /** On or off, as last asked for while a change is on its way. */
  enabled: boolean;
  toggleDisabled: boolean;
  onToggle: (enabled: boolean) => void;
  isTesting: boolean;
  testDisabled: boolean;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export const AIConnectionRow = ({
  connection,
  enabled,
  toggleDisabled,
  onToggle,
  isTesting,
  testDisabled,
  onTest,
  onEdit,
  onDelete,
}: AIConnectionRowProps) => {
  const { t, i18n } = useTranslation("settings");
  const failedSince = connection.last_error_at
    ? dateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(connection.last_error_at)
      )
    : null;

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-4 py-3">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{connection.label}</span>
          {connection.is_default && (
            <Badge variant="secondary">{t("aiConnections.defaultBadge")}</Badge>
          )}
          {!connection.model && <Badge variant="warning">{t("aiConnections.needsModel")}</Badge>}
        </div>
        <p className="text-muted-foreground text-sm">
          {PROVIDER_CONFIGS[connection.provider]?.label ?? connection.provider}
          {connection.model ? ` · ${connection.model}` : ""}
        </p>
        <p className="text-muted-foreground text-xs">
          {connection.has_api_key ? t("aiConnections.keySet") : t("aiConnections.noKey")}
          {connection.base_url ? ` · ${connection.base_url}` : ""}
        </p>
        {connection.communities.length > 0 && (
          <p className="text-muted-foreground text-xs">
            {t("aiConnections.servesOnly", {
              communities: listFormat(i18n.language, { type: "conjunction" }).format(
                connection.communities.map(
                  (community) =>
                    community.name ?? t("aiConnections.goneCommunity", { id: community.id })
                )
              ),
            })}
          </p>
        )}
        {connection.last_error && (
          <p className="text-destructive text-xs">
            {t("aiConnections.failingSince", {
              error: messageForCode(connection.last_error, "settings:ai.testError"),
              since: failedSince,
            })}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Switch
          aria-label={t("aiConnections.toggleLabel", { label: connection.label })}
          checked={enabled}
          onCheckedChange={onToggle}
          disabled={toggleDisabled}
        />
        <Button type="button" variant="outline" size="sm" onClick={onTest} disabled={testDisabled}>
          {isTesting ? t("ai.testing") : t("ai.testConnection")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("aiConnections.edit")}
          onClick={onEdit}
        >
          <Pencil className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("aiConnections.delete")}
          onClick={onDelete}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </div>
    </li>
  );
};

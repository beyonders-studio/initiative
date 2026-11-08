/**
 * The values a plug-in's settings hold in this community, which the plug-in
 * reads: the prefix of a task's reference, say.
 *
 * Each setting saves on its own. A unique one holds a value no other community
 * on this server holds, and the value it held before stays this community's:
 * the plug-in still reads it, so what was made with it keeps working. A value
 * that can't be used is refused with one message, whoever holds it.
 *
 * One renderer draws every plug-in's settings, from what its pinned definition
 * declares.
 */

import { Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginSettingRead } from "@/api/generated/initiativeAPI.schemas";
import { useUpdatePluginSetting } from "@/hooks/useCommunityPluginDetail";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { localized } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { listFormat } from "@/ui/lib/intl";

export interface PluginSettingsPanelProps {
  pluginId: number;
  settings: CommunityPluginSettingRead[];
}

export function PluginSettingsPanel({ pluginId, settings }: PluginSettingsPanelProps) {
  const { t } = useTranslation(["plugins"]);

  if (!settings.length) return null;

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("plugins:installSettings.title")}</h3>
        <p className="text-muted-foreground text-sm">{t("plugins:installSettings.description")}</p>
      </div>
      <div className="space-y-4 rounded-lg border p-4">
        {settings.map((setting) => (
          <SettingField key={setting.key} pluginId={pluginId} setting={setting} />
        ))}
      </div>
    </section>
  );
}

function SettingField({
  pluginId,
  setting,
}: {
  pluginId: number;
  setting: CommunityPluginSettingRead;
}) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const save = useUpdatePluginSetting(pluginId);
  // What the seat is typing, or `null` while the field shows what is held.
  const [draft, setDraft] = useState<string | null>(null);
  const language = i18n.resolvedLanguage ?? i18n.language;
  const id = `plugin-${pluginId}-setting-${setting.key}`;
  const value = draft ?? setting.value ?? "";
  const description = localized(setting.description, language);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(
      // An emptied field clears a setting that is not unique; a unique one
      // refuses it.
      { key: setting.key, value: value.trim() || null },
      {
        onSuccess: () => {
          setDraft(null);
          toast.success(t("plugins:installSettings.saved"));
        },
        onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
      }
    );
  };

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{localized(setting.label, language) ?? setting.key}</Label>
      {description && <p className="text-muted-foreground text-xs">{description}</p>}
      <form className="flex flex-wrap gap-2" onSubmit={submit}>
        <Input
          id={id}
          className="min-w-48 flex-1"
          autoComplete="off"
          placeholder={t("plugins:installSettings.notSet")}
          value={value}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          type="submit"
          disabled={draft === null || draft.trim() === (setting.value ?? "") || save.isPending}
        >
          {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("common:save")}
        </Button>
      </form>
      {setting.unique && (
        <p className="text-muted-foreground text-xs">{t("plugins:installSettings.unique")}</p>
      )}
      {setting.aliases.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("plugins:installSettings.earlier", {
            values: listFormat(language, { type: "unit", style: "short" }).format(setting.aliases),
          })}
        </p>
      )}
    </div>
  );
}

/**
 * `/settings/access` — who else can reach this tool entity.
 *
 * Write access to the entity is what the tab bar offers this section on, and
 * the section refuses it on its own too: the address is typeable, and sharing
 * is the last privilege gate in front of the entity's contents.
 *
 * Above who it is shared with, for someone who may share it: who has asked.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ShareControl } from "@/components/access/ShareControl";
import { ShareRequestsCard } from "@/components/access/ShareRequests";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { toast } from "@/lib/mascotToast";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { Field } from "@/ui/field";
import { Textarea } from "@/ui/textarea";

import { useToolSettings } from "./ToolSettingsContext";

/** Mirrors the backend's limit on the note, which is the authority. */
const NOTE_MAX_LENGTH = 1000;

export const AccessPage = () => {
  const { t } = useTranslation(["common", "access"]);
  const { tool, entity, setGrants } = useToolSettings();
  // Said to whoever the next change lets in, then cleared.
  const [note, setNote] = useState("");

  if (!entity.can.edit) {
    return <SettingsPermissionRequired scope="tool" />;
  }

  const ownerId = entity.grants.find((grant) => grant.level === "owner")?.user_id ?? null;

  return (
    <div className="space-y-6">
      {entity.can.share ? <ShareRequestsCard tool={tool} entityId={entity.id} /> : null}
      <Card>
        <CardHeader>
          <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {entity.can.share ? (
            <Field label={t("access:share.noteLabel")} className="mb-4">
              <Textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t("access:share.notePlaceholder")}
                maxLength={NOTE_MAX_LENGTH}
                rows={2}
                disabled={setGrants.isPending}
              />
            </Field>
          ) : null}
          <ShareControl
            initiativeId={entity.initiative_id ?? 0}
            grants={entity.grants}
            ownerId={ownerId}
            ownerPlugin={entity.owner_plugin ?? null}
            onChange={(grants) =>
              setGrants.mutate(
                { grants, note: note.trim() || null },
                {
                  onSuccess: () => {
                    setNote("");
                    toast.success(t("common:toolSettings.permissionsUpdated"));
                  },
                }
              )
            }
            disabled={!entity.can.share || setGrants.isPending}
          />
        </CardContent>
      </Card>
    </div>
  );
};

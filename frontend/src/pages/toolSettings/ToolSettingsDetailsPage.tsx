/**
 * `/settings` — what a tool entity is called, what it is tagged with, its
 * custom properties, and whether it carries a comment thread.
 *
 * The section every tool's settings open on, so it is served at `/settings`
 * itself rather than at a `/settings/details` alias.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagPicker } from "@/components/tags";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { ToolTemplateCard } from "@/components/tools/settings/ToolTemplateCard";
import { propertySaves } from "@/hooks/useProperties";
import { useServerForm } from "@/hooks/useServerForm";
import { useSetToolComments } from "@/hooks/useToolComments";
import { useSetToolTags } from "@/hooks/useToolTags";
import { PropertiesField } from "@/lib/layouts/fieldEditors";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

export const ToolSettingsDetailsPage = () => {
  const { t } = useTranslation(["common", "properties"]);
  const { tool, entity, update, detailsExtra, detailsInline } = useToolSettings();
  const canManage = entity.can.edit;

  // Name and description wait for Save, so a refetch arriving mid-sentence
  // must not take the sentence away.
  const details = useServerForm(
    entity,
    (loaded) => ({
      name: loaded?.name ?? "",
      description: loaded?.description ?? "",
    }),
    entity.id
  );

  // The rest are written the moment they are changed, so the local copy is
  // only the preview and the server stays the truth.
  const [tags, setTags] = useState<TagSummary[]>(entity.tags ?? []);
  const [commentsEnabled, setCommentsEnabled] = useState(entity.comments_enabled);

  const [prevEntity, setPrevEntity] = useState(entity);
  if (prevEntity !== entity) {
    setPrevEntity(entity);
    setTags(entity.tags ?? []);
    setCommentsEnabled(entity.comments_enabled);
  }

  const setToolTags = useSetToolTags(tool);
  const setToolComments = useSetToolComments(tool);
  // A wiki's switch governs the threads on its PAGES, which is not what a
  // card labelled with the wiki's name reads as. Held back until it is
  // offered where the pages are.
  const showsCommentSwitch = tool !== Tool.wiki;

  const handleDetailsSave = () => {
    // What is being sent, so anything typed while this is in flight is not
    // counted as saved by it.
    const sent = details.values;
    const trimmedName = sent.name.trim();
    if (!trimmedName) return;
    update?.mutate(
      { name: trimmedName, description: sent.description.trim() || null },
      {
        onSuccess: () => {
          details.settle(sent);
          toast.success(t("toolSettings.detailsUpdated"));
        },
      }
    );
  };

  return (
    <div className="space-y-6">
      {update && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <Field label={t("name")}>
              <Input
                value={details.values.name}
                onChange={(e) => details.set({ name: e.target.value })}
                placeholder={t("toolSettings.namePlaceholder")}
                disabled={!canManage}
              />
            </Field>
            <Field label={t("description")}>
              <Textarea
                value={details.values.description}
                onChange={(e) => details.set({ description: e.target.value })}
                placeholder={t("toolSettings.descriptionPlaceholder")}
                disabled={!canManage}
                rows={3}
              />
            </Field>
            {canManage && (
              <Button
                onClick={handleDetailsSave}
                disabled={update.isPending || !details.values.name.trim()}
              >
                {update.isPending ? t("toolSettings.saving") : t("save")}
              </Button>
            )}
            {detailsInline && <div className="border-t pt-4">{detailsInline}</div>}
          </CardContent>
        </Card>
      )}

      {detailsExtra}

      <ToolTemplateCard />

      <Card>
        <CardHeader>
          <CardTitle>{t("toolSettings.tags")}</CardTitle>
          <CardDescription>{t("toolSettings.tagsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {canManage ? (
            <TagPicker
              selectedTags={tags}
              onChange={(newTags) => {
                // Tags persist on pick rather than with a Save button, so the
                // picker shows the new selection immediately and puts the old
                // one back if the write fails.
                const previous = tags;
                setTags(newTags);
                setToolTags.mutate(
                  { id: entity.id, tagIds: newTags.map((tag) => tag.id) },
                  { onError: () => setTags(previous) }
                );
              }}
            />
          ) : (
            <p className="text-muted-foreground text-sm">{t("toolSettings.tagsNoAccess")}</p>
          )}
        </CardContent>
      </Card>

      {/* Definitions belong to an initiative, so a community-level tool has none
          to offer. */}
      {entity.initiative_id !== null && (
        <Card>
          <CardHeader>
            <CardTitle>{t("properties:title")}</CardTitle>
            <CardDescription>{t("toolSettings.propertiesDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <PropertiesField
              kind={propertySaves[PropertyTarget[tool]]}
              id={entity.id}
              properties={entity.properties ?? []}
              readOnly={!canManage}
              initiativeId={entity.initiative_id}
              canOpen={{ tool, id: entity.id }}
              updatedAt={entity.updated_at}
              hideLabel
            />
          </CardContent>
        </Card>
      )}

      {showsCommentSwitch && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-4">
            <div>
              <CardTitle>{t("toolSettings.comments")}</CardTitle>
              <CardDescription>{t("toolSettings.commentsDescription")}</CardDescription>
            </div>
            <Switch
              id="tool-settings-comments-enabled"
              checked={commentsEnabled}
              onCheckedChange={(value) => {
                // Saved on flip rather than behind the Save button above, like
                // the tag picker: the switch shows the new state immediately and
                // puts the old one back if the write fails.
                const previous = commentsEnabled;
                setCommentsEnabled(value);
                setToolComments.mutate(
                  { id: entity.id, enabled: value },
                  { onError: () => setCommentsEnabled(previous) }
                );
              }}
              disabled={!canManage || setToolComments.isPending}
              aria-label={t("toolSettings.commentsToggle")}
            />
          </CardHeader>
        </Card>
      )}
    </div>
  );
};

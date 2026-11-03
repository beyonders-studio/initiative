/**
 * The bar under a tool page's title: what the tool is (its status, its tags,
 * its properties) and what only this tool has, side by side in one strip.
 *
 * Status, tags and properties are on every tool, so they are always here, in
 * that order around whatever the tool adds. The properties open below the
 * strip. Exports and filters are not part of it; they stay with the list or
 * view they act on.
 *
 * It runs edge to edge under the page header, and on a narrow screen the strip
 * scrolls sideways rather than wrapping, with a scrollbar along its foot to say
 * so. The header sets `--chest-gutter` to where the page's own column starts,
 * so the first segment lines up with the title above it.
 */
import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ArchivableType,
  type PropertySummary,
  PropertyTarget,
  type TagSummary,
  type Tool,
  type ToolCan,
} from "@/api/generated/initiativeAPI.schemas";
import { ownProperties } from "@/components/properties/propertyHelpers";
import { TagBadge, TagPicker } from "@/components/tags";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { propertySaves } from "@/hooks/useProperties";
import { useSetToolTags } from "@/hooks/useToolTags";
import { useCommunityPath } from "@/lib/communityUrl";
import { PropertiesField } from "@/lib/layouts/fieldEditors";
import { toast } from "@/lib/mascotToast";
import { cn } from "@/lib/utils";

export interface ToolChestEntity {
  id: number;
  name: string;
  initiative_id: number | null;
  archived_at: string | null;
  tags: TagSummary[];
  properties?: PropertySummary[];
  can: Pick<ToolCan, "edit" | "unarchive">;
}

/** A tool that can be a template (projects and files): whether it is one,
 *  and how to change that. */
export interface ToolChestTemplate {
  isTemplate: boolean;
  onChange: (isTemplate: boolean) => Promise<unknown>;
}

/** A kind inside a tool that keeps its own status, tags and properties (a
 *  collection, in Files): what it is archived as, and how its properties and
 *  tags are saved. */
export interface ToolChestKind {
  archivable: ArchivableType;
  properties: (typeof propertySaves)[PropertyTarget];
  saveTags: (tagIds: number[]) => Promise<unknown>;
}

export interface ToolChestProps {
  tool: Tool;
  entity: ToolChestEntity;
  /** Adds Template to the status, for a tool that can be one. */
  template?: ToolChestTemplate;
  /** The page is of a kind inside the tool rather than of the tool itself. */
  kind?: ToolChestKind;
  /** What only this tool has: its own data and buttons, as `ToolChestSegment`s. */
  children?: ReactNode;
}

/** One part of the strip: its label over its value, or just the tool's own
 *  buttons. */
export const ToolChestSegment = ({
  label,
  children,
}: {
  label?: ReactNode;
  children: ReactNode;
}) => (
  <div className="flex shrink-0 flex-col justify-center gap-1 px-4 py-2.5 text-sm first:pl-0 md:flex-row md:items-center md:justify-start md:gap-2 md:py-2">
    {label ? <span className="font-medium text-muted-foreground text-xs">{label}</span> : null}
    <div className="flex items-center gap-2 whitespace-nowrap">{children}</div>
  </div>
);

export const ToolChest = ({ tool, entity, template, kind, children }: ToolChestProps) => {
  const { t } = useTranslation(["common", "properties"]);
  const gp = useCommunityPath();
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [tags, setTags] = useState(entity.tags);
  const setToolTags = useSetToolTags(tool);
  const canEdit = entity.can.edit;
  // Definitions belong to an initiative, so a community-level tool has none.
  const hasProperties = entity.initiative_id !== null;
  const propertyCount = ownProperties(entity.properties ?? []).length;

  return (
    <div className="border-y bg-background/60 md:rounded-lg md:border md:bg-card">
      {/* The strip scrolls; the properties toggle stays out of it, at its end
          on a wide screen and on its own row under it on a narrow one. */}
      <div className="flex flex-col md:flex-row">
        <ScrollArea type="auto" className="min-w-0 flex-1">
          <div
            className={cn(
              "flex items-stretch divide-x",
              "pl-[var(--chest-gutter,1rem)]",
              hasProperties ? "pr-4 md:pr-0" : "pr-[var(--chest-gutter-right,1rem)]"
            )}
          >
            <ToolChestSegment label={t("toolChest.status")}>
              <ToolStatus
                archivable={kind?.archivable ?? (tool as ArchivableType)}
                entity={entity}
                template={template}
              />
            </ToolChestSegment>
            {children}
            <ToolChestSegment label={t("toolSettings.tags")}>
              {canEdit ? (
                <TagPicker
                  selectedTags={tags}
                  className="min-w-40 whitespace-normal"
                  onChange={(next) => {
                    // Saved on pick, and put back if the write fails.
                    const previous = tags;
                    setTags(next);
                    const tagIds = next.map((tag) => tag.id);
                    (kind
                      ? kind.saveTags(tagIds)
                      : setToolTags.mutateAsync({ id: entity.id, tagIds })
                    ).catch(() => setTags(previous));
                  }}
                />
              ) : tags.length > 0 ? (
                <span className="flex gap-1">
                  {tags.map((tag) => (
                    <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                  ))}
                </span>
              ) : (
                <span className="text-muted-foreground">{t("toolChest.none")}</span>
              )}
            </ToolChestSegment>
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
        {hasProperties ? (
          <button
            type="button"
            onClick={() => setPropertiesOpen((open) => !open)}
            aria-expanded={propertiesOpen}
            className={cn(
              "flex shrink-0 items-center gap-2 border-t py-2.5 text-left text-sm hover:bg-accent/50",
              "pr-[var(--chest-gutter-right,1rem)] pl-[var(--chest-gutter,1rem)]",
              "md:border-t-0 md:border-l md:py-2 md:pl-4"
            )}
          >
            <span className="font-medium text-muted-foreground text-xs">
              {t("properties:title")}
            </span>
            <span className="flex items-center gap-1 tabular-nums">
              {propertyCount}
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", propertiesOpen && "rotate-180")}
                aria-hidden
              />
            </span>
          </button>
        ) : null}
      </div>
      {hasProperties && propertiesOpen ? (
        <div className="border-t py-3 pr-[var(--chest-gutter-right,1rem)] pl-[var(--chest-gutter,1rem)]">
          <PropertiesField
            kind={kind?.properties ?? propertySaves[PropertyTarget[tool]]}
            id={entity.id}
            properties={entity.properties ?? []}
            readOnly={!canEdit}
            initiativeId={entity.initiative_id as number}
            canOpen={kind ? undefined : { tool, id: entity.id }}
            hideLabel
          />
        </div>
      ) : null}
    </div>
  );
};

type Status = "active" | "template" | "archived";

const STATUS_DOT: Record<Status, string> = {
  active: "bg-success",
  template: "bg-primary",
  archived: "bg-muted-foreground",
};

const StatusLabel = ({ status }: { status: Status }) => {
  const { t } = useTranslation("common");
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      <span className={cn("h-2 w-2 rounded-full", STATUS_DOT[status])} aria-hidden />
      {t(`toolChest.${status}`)}
    </span>
  );
};

/** Active, a template (for a tool that can be one), or archived; someone who
 *  may change it picks another here, the way Settings would. Archiving is an
 *  ordinary edit, and the way back out is its own permission. An archived
 *  template stays a template, so it reads as archived until it comes back. */
const ToolStatus = ({
  archivable,
  entity,
  template,
}: {
  archivable: ArchivableType;
  entity: ToolChestEntity;
  template?: ToolChestTemplate;
}) => {
  const { t } = useTranslation("common");
  const archived = entity.archived_at !== null;
  const status: Status = archived ? "archived" : template?.isTemplate ? "template" : "active";
  const [changing, setChanging] = useState(false);
  const archive = useArchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.archived", { name: entity.name })),
  });
  const unarchive = useUnarchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.unarchived", { name: entity.name })),
  });
  const canChange = archived ? entity.can.unarchive : entity.can.edit;

  if (!canChange) return <StatusLabel status={status} />;

  const change = async (next: Status) => {
    if (next === status) return;
    const target = { entityType: archivable, entityId: entity.id };
    setChanging(true);
    try {
      if (next === "archived") {
        await archive.mutateAsync(target);
        return;
      }
      // Out of the archive first: nothing on an archived row may be edited.
      if (archived) await unarchive.mutateAsync(target);
      const wantTemplate = next === "template";
      if (template && template.isTemplate !== wantTemplate) {
        await template.onChange(wantTemplate);
      }
    } catch {
      // Each mutation reports its own error.
    } finally {
      setChanging(false);
    }
  };

  const options: Status[] = template ? ["active", "template", "archived"] : ["active", "archived"];

  return (
    <Select
      value={status}
      disabled={changing}
      onValueChange={(next) => void change(next as Status)}
    >
      <SelectTrigger
        aria-label={t("toolChest.status")}
        className="h-7 w-auto gap-1 border-none bg-transparent px-1.5 shadow-none"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option} value={option}>
            <StatusLabel status={option} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};

import { useTranslation } from "react-i18next";

import type { EndpointRef } from "@/api/generated/initiativeAPI.schemas";
import { EntityCard } from "@/components/entities/EntityCard";
import { EntityPicker } from "@/components/entities/EntityPicker";
import { type LinkedRef, refKey } from "@/lib/relationships";
import { Label } from "@/ui/label";

interface EntityLinkFieldProps {
  label: string;
  /** The thing being linked from. Absent while it does not exist yet. */
  subject?: EndpointRef;
  initiativeId: number;
  value: LinkedRef[];
  onChange: (next: LinkedRef[]) => void;
  readOnly?: boolean;
}

/**
 * A list of linked things, of any kind, edited in place.
 *
 * It is controlled: the owning form holds the value and decides when to save,
 * because a form saves on submit rather than on each pick, and may be editing a
 * thing that does not exist yet.
 *
 * Picking appends. The combobox never holds a value of its own, which is how the
 * one underneath it already behaves.
 */
export const EntityLinkField = ({
  label,
  subject,
  initiativeId,
  value,
  onChange,
  readOnly,
}: EntityLinkFieldProps) => {
  const { t } = useTranslation(["relations", "search"]);
  const chosen = new Set(value.map(refKey));

  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {readOnly ? null : (
        <EntityPicker
          subject={subject}
          initiativeId={initiativeId}
          value={null}
          onChange={(picked) => {
            if (!picked) return;
            const ref: LinkedRef = {
              type: picked.entity_type,
              id: picked.entity_id,
              title: picked.title,
              toolTitle: picked.tool_title,
            };
            if (chosen.has(refKey(ref))) return;
            onChange([...value, ref]);
          }}
        />
      )}
      {value.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("relations:groups.attached.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {value.map((ref) => (
            <li key={refKey(ref)}>
              {/* The same row the relations section draws, so a thing looks the
                  same wherever it is linked from. There is no link yet to carry
                  a date, and nothing to route a child kind by, so this says what
                  it knows and no more. */}
              <EntityCard
                variant="compact"
                end={{
                  type: ref.type,
                  id: ref.id,
                  title: ref.title,
                  initiative_id: initiativeId,
                  updated_at: null,
                  tool: null,
                  tool_id: null,
                  tool_title: ref.toolTitle ?? null,
                  image_urls: [],
                  icon: null,
                  color: null,
                  file_type: null,
                  mime_type: null,
                  original_filename: null,
                  smart_link_url: null,
                  handle: null,
                  is_open: null,
                  starts_at: null,
                }}
                onRemove={
                  readOnly
                    ? undefined
                    : () => onChange(value.filter((row) => refKey(row) !== refKey(ref)))
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

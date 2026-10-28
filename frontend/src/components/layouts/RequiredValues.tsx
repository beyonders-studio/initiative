import { type ReactNode, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  DetailLayoutRead,
  GetLayoutsParams,
  PropertyDefinitionRead,
  PropertyValueInput,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyInput } from "@/components/properties/PropertyInput";
import { isEmptyPropertyValue } from "@/components/properties/propertyHelpers";
import { TagPicker } from "@/components/tags";
import { Label } from "@/components/ui/label";
import { detailLayoutOf, useToolLayouts } from "@/hooks/useToolLayouts";
import { missingRequired, requiredKeys, type StoredRegions } from "@/lib/layouts/detailLayout";
import { PROPERTY_FIELD_PREFIX } from "@/lib/layouts/fields";

/** What a target's page of `kind` requires, in the order it places them:
 *  nothing while it is drawn as shipped. */
export const useRequiredKeys = (
  target: GetLayoutsParams | null,
  kind: DetailLayoutRead["kind"]
) => {
  const { data, isLoading } = useToolLayouts(target);
  const keys = useMemo(
    () => requiredKeys(detailLayoutOf(data, kind) as StoredRegions | null),
    [data, kind]
  );
  return { keys, isLoading };
};

/** The values asked for, by property id, and the tags. */
export interface RequiredDraft {
  values: ReadonlyMap<number, unknown>;
  tags: TagSummary[];
}

export const EMPTY_REQUIRED: RequiredDraft = { values: new Map(), tags: [] };

const propertyId = (key: string) => Number(key.slice(PROPERTY_FIELD_PREFIX.length));

/** What of `keys` a draft leaves empty: a property while `definitions` still
 *  has it. */
export const missingIn = (
  keys: readonly string[],
  draft: RequiredDraft,
  definitions: readonly PropertyDefinitionRead[] | undefined
): string[] =>
  missingRequired(
    keys,
    (key) =>
      key === "tags"
        ? draft.tags.length > 0
        : !isEmptyPropertyValue(draft.values.get(propertyId(key))),
    definitions
  );

/** The values a draft gives, as a create sends them. */
export const valuesOf = (draft: RequiredDraft): PropertyValueInput[] =>
  [...draft.values].map(([property_id, value]) => ({ property_id, value }));

const Asked = ({ id, label, children }: { id: string; label: string; children: ReactNode }) => {
  const { t } = useTranslation("layouts");
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <Label id={`${id}-label`} htmlFor={id}>
          {label}
        </Label>
        <span className="text-muted-foreground text-xs">{t("required.label")}</span>
      </div>
      <fieldset aria-labelledby={`${id}-label`} className="min-w-0">
        {children}
      </fieldset>
    </div>
  );
};

/**
 * What a page requires of something being added, where the form adding it
 * asks for nothing else of the kind: its tags, and each property or metadata
 * by its key, as the layout places them. A key it cannot ask for (a property
 * since deleted) is left out.
 */
export const RequiredValues = ({
  keys,
  definitions,
  draft,
  onChange,
  initiativeId,
  idPrefix,
}: {
  keys: readonly string[];
  definitions: readonly PropertyDefinitionRead[];
  draft: RequiredDraft;
  onChange: (next: RequiredDraft) => void;
  initiativeId: number;
  idPrefix: string;
}) => {
  const { t } = useTranslation("common");
  const byId = new Map(definitions.map((definition) => [definition.id, definition]));
  return keys.map((key) => {
    const id = `${idPrefix}-${key.replace(":", "-")}`;
    if (key === "tags") {
      return (
        <Asked key={key} id={id} label={t("toolSettings.tags")}>
          <TagPicker
            id={id}
            selectedTags={draft.tags}
            onChange={(tags) => onChange({ ...draft, tags })}
          />
        </Asked>
      );
    }
    const definition = key.startsWith(PROPERTY_FIELD_PREFIX) ? byId.get(propertyId(key)) : null;
    if (!definition) return null;
    return (
      <Asked key={key} id={id} label={definition.name}>
        <PropertyInput
          definition={definition}
          value={draft.values.get(definition.id) ?? null}
          onChange={(value) =>
            onChange({ ...draft, values: new Map(draft.values).set(definition.id, value) })
          }
          initiativeId={initiativeId}
        />
      </Asked>
    );
  });
};

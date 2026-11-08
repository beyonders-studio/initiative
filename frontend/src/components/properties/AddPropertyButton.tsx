import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { type MetadataOwner, useOwnedDefinitions } from "@/hooks/useProperties";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";

import { NewPropertyForm } from "./NewPropertyForm";
import { iconForPropertyType } from "./propertyTypeIcons";

export interface AddPropertyButtonProps {
  /**
   * Initiative the entity belongs to. Scopes both the candidate list (so the
   * picker only surfaces definitions from this initiative) and the inline
   * "create new property" submission (bakes ``initiative_id`` into the create
   * payload).
   */
  initiativeId: number;
  /** The project whose metadata the item may also hold (a task's), offered
   *  beside the properties and made from here as well. */
  owner?: MetadataOwner;
  currentPropertyIds: number[];
  onAdd: (definition: PropertyDefinitionRead) => void;
  disabled?: boolean;
}

/** Whether a definition is a project's or a collection's metadata rather than
 *  one of the initiative's properties. */
const isOwned = (definition: PropertyDefinitionRead) =>
  definition.project_id !== null || definition.collection_id !== null;

export const AddPropertyButton = ({
  initiativeId,
  owner,
  currentPropertyIds,
  onAdd,
  disabled = false,
}: AddPropertyButtonProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const [open, setOpen] = useState(false);
  // The new property's name while it is being made, in place of the list.
  const [newName, setNewName] = useState<string | null>(null);

  const propertiesQuery = useOwnedDefinitions({ initiativeId, owner });

  // The owner's metadata, then the initiative's properties, each under its
  // own heading where there are both.
  const candidates = useMemo(() => {
    const all = (propertiesQuery.data ?? []).filter(
      (definition) => !currentPropertyIds.includes(definition.id)
    );
    return [...all.filter(isOwned), ...all.filter((definition) => !isOwned(definition))];
  }, [propertiesQuery.data, currentPropertyIds]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) setNewName(null);
  };

  return (
    <Combobox
      items={candidates.map((definition) => ({
        value: String(definition.id),
        label: definition.name,
        icon: iconForPropertyType(definition.type),
        sublabel: t(`properties:types.${definition.type}`),
        group: owner
          ? t(
              isOwned(definition)
                ? `properties:picker.owner.${owner.kind}`
                : "properties:picker.owner.initiative"
            )
          : undefined,
      }))}
      onValueChange={(value) => {
        const definition = candidates.find((each) => String(each.id) === value);
        if (definition) onAdd(definition);
      }}
      open={open}
      onOpenChange={handleOpenChange}
      // Offered whatever was typed: a new property starts from the search.
      typedLabel={() => t("properties:picker.createHeading")}
      onCreate={setNewName}
      loading={propertiesQuery.isLoading}
      searchPlaceholder={t("properties:picker.placeholder")}
      emptyMessage={t("properties:picker.empty")}
      disabled={disabled}
      trigger={
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted-foreground hover:text-foreground"
          disabled={disabled}
        >
          <Plus className="h-4 w-4" />
          {t(owner ? "properties:addPropertyOrMetadata" : "properties:addMetadata")}
        </Button>
      }
    >
      {newName !== null ? (
        <NewPropertyForm
          initiativeId={initiativeId}
          owner={owner}
          name={newName}
          onCreated={(created) => {
            onAdd(created);
            handleOpenChange(false);
          }}
          onCancel={() => setNewName(null)}
        />
      ) : null}
    </Combobox>
  );
};

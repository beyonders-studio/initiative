import { Plus } from "lucide-react";
import { type ComponentProps, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";

import { type CreateProperty, NewPropertyForm } from "./NewPropertyForm";
import { iconForPropertyType } from "./propertyTypeIcons";

export interface AddPropertyButtonProps {
  /** What can be added: the initiative's properties, and the owner's
   *  metadata where there is an owner. */
  definitions: PropertyDefinitionRead[];
  /** While the definitions are being read. */
  loading?: boolean;
  /** The initiative a property made from here is made in. */
  initiativeId: number;
  /** The project whose metadata the item may also hold (a task's), offered
   *  beside the properties and made from here as well. */
  owner?: ComponentProps<typeof NewPropertyForm>["owner"];
  /** Makes a property named from here. */
  create: CreateProperty;
  currentPropertyIds: number[];
  onAdd: (definition: PropertyDefinitionRead) => void;
  disabled?: boolean;
}

/** Whether a definition is a project's or a collection's metadata rather than
 *  one of the initiative's properties. */
const isOwned = (definition: PropertyDefinitionRead) =>
  definition.project_id !== null || definition.collection_id !== null;

export const AddPropertyButton = ({
  definitions,
  loading = false,
  initiativeId,
  owner,
  create,
  currentPropertyIds,
  onAdd,
  disabled = false,
}: AddPropertyButtonProps) => {
  const { t } = useTranslation("properties");
  const [open, setOpen] = useState(false);
  // The new property's name while it is being made, in place of the list.
  const [newName, setNewName] = useState<string | null>(null);

  // The owner's metadata, then the initiative's properties, each under its
  // own heading where there are both.
  const candidates = useMemo(() => {
    const all = definitions.filter((definition) => !currentPropertyIds.includes(definition.id));
    return [...all.filter(isOwned), ...all.filter((definition) => !isOwned(definition))];
  }, [definitions, currentPropertyIds]);

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
        sublabel: t(`types.${definition.type}`),
        group: owner
          ? t(isOwned(definition) ? `picker.owner.${owner.kind}` : "picker.owner.initiative")
          : undefined,
      }))}
      onValueChange={(value) => {
        const definition = candidates.find((each) => String(each.id) === value);
        if (definition) onAdd(definition);
      }}
      open={open}
      onOpenChange={handleOpenChange}
      // Offered whatever was typed: a new property starts from the search.
      typedLabel={() => t("picker.createHeading")}
      onCreate={setNewName}
      loading={loading}
      searchPlaceholder={t("picker.placeholder")}
      emptyMessage={t("picker.empty")}
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
          {t(owner ? "addPropertyOrMetadata" : "addMetadata")}
        </Button>
      }
    >
      {newName !== null ? (
        <NewPropertyForm
          initiativeId={initiativeId}
          owner={owner}
          create={create}
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

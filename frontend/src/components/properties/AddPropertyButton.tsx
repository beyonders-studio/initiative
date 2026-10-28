import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type MetadataOwner, useOwnedDefinitions } from "@/hooks/useProperties";

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
  const [search, setSearch] = useState("");

  // The inline "create a property" form, in place of the list.
  const [isCreating, setIsCreating] = useState(false);

  const propertiesQuery = useOwnedDefinitions({ initiativeId, owner });

  const currentIdSet = useMemo(() => new Set(currentPropertyIds), [currentPropertyIds]);

  const candidates = useMemo(() => {
    const all = propertiesQuery.data ?? [];
    return all.filter((definition) => !currentIdSet.has(definition.id));
  }, [propertiesQuery.data, currentIdSet]);

  const filteredCandidates = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return candidates;
    return candidates.filter((definition) => definition.name.toLowerCase().includes(term));
  }, [candidates, search]);
  // The owner's metadata, then the initiative's properties, each under its
  // own heading where there are both.
  const groups = [
    {
      key: "metadata",
      heading: owner ? t(`properties:picker.owner.${owner.kind}`) : undefined,
      items: filteredCandidates.filter((definition) => isOwned(definition)),
    },
    {
      key: "properties",
      heading: owner ? t("properties:picker.owner.initiative") : undefined,
      items: filteredCandidates.filter((definition) => !isOwned(definition)),
    },
  ].filter((group) => group.items.length > 0);

  const handleOpenChange = useCallback((next: boolean) => {
    setOpen(next);
    if (!next) {
      setSearch("");
      setIsCreating(false);
    }
  }, []);

  const startCreating = useCallback(() => setIsCreating(true), []);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
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
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        {isCreating ? (
          <NewPropertyForm
            initiativeId={initiativeId}
            owner={owner}
            name={search.trim()}
            onCreated={(created) => {
              onAdd(created);
              handleOpenChange(false);
            }}
            onCancel={() => setIsCreating(false)}
          />
        ) : (
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={t("properties:picker.placeholder")}
              value={search}
              onValueChange={setSearch}
            />
            <CommandList>
              {propertiesQuery.isLoading ? (
                <div className="py-6 text-center text-muted-foreground text-sm">
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  {filteredCandidates.length === 0 ? (
                    <div className="py-6 text-center text-muted-foreground text-sm">
                      {t("properties:picker.empty")}
                    </div>
                  ) : (
                    groups.map((group) => (
                      <CommandGroup key={group.key} heading={group.heading}>
                        {group.items.map((definition) => {
                          const Icon = iconForPropertyType(definition.type);
                          return (
                            <CommandItem
                              key={definition.id}
                              value={`property-${definition.id}`}
                              onSelect={() => {
                                onAdd(definition);
                                handleOpenChange(false);
                              }}
                              className="cursor-pointer"
                            >
                              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                              <div className="flex flex-col">
                                <span>{definition.name}</span>
                                <span className="text-muted-foreground text-xs">
                                  {t(`properties:types.${definition.type}`)}
                                </span>
                              </div>
                            </CommandItem>
                          );
                        })}
                      </CommandGroup>
                    ))
                  )}
                  <CommandSeparator />
                  <CommandGroup>
                    <CommandItem
                      key="create-new"
                      value="create-new"
                      onSelect={startCreating}
                      className="cursor-pointer"
                    >
                      <Plus className="h-4 w-4" />
                      {t("properties:picker.createHeading")}
                    </CommandItem>
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
};

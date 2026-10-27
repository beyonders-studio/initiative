import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CurrencyCode,
  type PropertyDefinitionCreate,
  type PropertyDefinitionRead,
  type PropertyOption,
  PropertyType,
  type PropertyType as PropertyTypeValue,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { useCreateProperty } from "@/hooks/useProperties";

import { CurrencySelect, useDefaultCurrency } from "./CurrencySelect";
import { normalizeOptionList, typeRequiresOptions } from "./propertyHelpers";
import { iconForPropertyType } from "./propertyTypeIcons";

/** The kinds of property there are, in the order they are offered. */
export const PROPERTY_TYPES: PropertyTypeValue[] = [
  PropertyType.text,
  PropertyType.number,
  PropertyType.checkbox,
  PropertyType.date,
  PropertyType.datetime,
  PropertyType.url,
  PropertyType.select,
  PropertyType.multi_select,
  PropertyType.user_reference,
  PropertyType.currency,
  PropertyType.rating,
];

/**
 * A new property for an initiative, or a field of one of its collections: its
 * name, its kind and, for a select, its options, for money its currency. Where
 * an item's properties are added to, and where a layout adds a field, it is
 * the one way a property is made there.
 */
export const NewPropertyForm = ({
  initiativeId,
  collectionId,
  name: startName = "",
  type: startType = PropertyType.text,
  onCreated,
  onCancel,
  onPendingChange,
}: {
  initiativeId: number;
  /** The collection it is a field of; left out, it is the initiative's. */
  collectionId?: number;
  /** What the name starts as: what was searched for, say. */
  name?: string;
  /** The kind it starts as. */
  type?: PropertyTypeValue;
  onCreated: (definition: PropertyDefinitionRead) => void;
  onCancel: () => void;
  /** Told when creating starts and ends. */
  onPendingChange?: (pending: boolean) => void;
}) => {
  const { t } = useTranslation(["properties", "common"]);
  const [newName, setNewName] = useState(startName);
  const [newType, setNewType] = useState<PropertyTypeValue>(startType);
  const [newOptions, setNewOptions] = useState<PropertyOption[]>(() =>
    typeRequiresOptions(startType) ? [{ value: "", label: "" }] : []
  );
  const defaultCurrency = useDefaultCurrency();
  const [newCurrency, setNewCurrency] = useState<CurrencyCode>(defaultCurrency);
  const createPropertyMutation = useCreateProperty();

  const handleAddOption = () => setNewOptions((prev) => [...prev, { value: "", label: "" }]);
  const handleOptionChange = (index: number, patch: Partial<PropertyOption>) =>
    setNewOptions((prev) =>
      prev.map((option, i) => (i === index ? { ...option, ...patch } : option))
    );
  const handleOptionRemove = (index: number) =>
    setNewOptions((prev) => prev.filter((_, i) => i !== index));

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    let options: PropertyOption[] | undefined;
    if (typeRequiresOptions(newType)) {
      options = normalizeOptionList(newOptions);
      if (options.length === 0) return;
    }
    const payload: PropertyDefinitionCreate = {
      name,
      type: newType,
      initiative_id: initiativeId,
      ...(collectionId !== undefined ? { collection_id: collectionId } : {}),
      options,
      ...(newType === PropertyType.currency ? { currency: newCurrency } : {}),
    };
    onPendingChange?.(true);
    try {
      onCreated(await createPropertyMutation.mutateAsync(payload));
    } catch {
      // toast handled inside the mutation hook
    } finally {
      onPendingChange?.(false);
    }
  };

  const canSubmit = useMemo(() => {
    if (!newName.trim()) return false;
    if (typeRequiresOptions(newType)) {
      return normalizeOptionList(newOptions).length > 0;
    }
    return true;
  }, [newName, newType, newOptions]);

  return (
    <div className="space-y-3 p-3">
      <div className="font-medium text-sm">{t("properties:picker.createHeading")}</div>
      <div className="space-y-2">
        <Label htmlFor="property-new-name" className="font-normal text-xs">
          {t("properties:picker.namePlaceholder")}
        </Label>
        <Input
          id="property-new-name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder={t("properties:picker.namePlaceholder")}
          autoFocus
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="property-new-type" className="font-normal text-xs">
          {t("properties:picker.typeLabel")}
        </Label>
        <Select
          value={newType}
          onValueChange={(value) => {
            const nextType = value as PropertyTypeValue;
            setNewType(nextType);
            if (!typeRequiresOptions(nextType)) {
              setNewOptions([]);
            } else if (newOptions.length === 0) {
              setNewOptions([{ value: "", label: "" }]);
            }
          }}
        >
          <SelectTrigger id="property-new-type">
            <div className="flex min-w-0 items-center gap-2">
              {(() => {
                const Icon = iconForPropertyType(newType);
                return <Icon className="h-4 w-4 shrink-0" />;
              })()}
              <span className="truncate">{t(`properties:types.${newType}`)}</span>
            </div>
          </SelectTrigger>
          <SelectContent>
            {PROPERTY_TYPES.map((typeValue) => {
              const Icon = iconForPropertyType(typeValue);
              const label = t(`properties:types.${typeValue}`);
              return (
                <SelectItem key={typeValue} value={typeValue} textValue={label}>
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{label}</span>
                  </div>
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </div>

      {newType === PropertyType.currency ? (
        <div className="space-y-2">
          <Label className="font-normal text-xs">{t("properties:currency.label")}</Label>
          <CurrencySelect value={newCurrency} onChange={setNewCurrency} />
        </div>
      ) : null}

      {typeRequiresOptions(newType) ? (
        <div className="space-y-2">
          <Label className="font-normal text-xs">{t("properties:manager.optionsLabel")}</Label>
          <ul className="space-y-2">
            {newOptions.map((option, index) => (
              // Key by index, not by the edited field: keying on
              // ``option.value``/``label`` remounts the input on every
              // keystroke and steals focus. Inputs are controlled and
              // rows only change via add/remove, so the index is correct.
              // biome-ignore lint/suspicious/noArrayIndexKey: controlled rows with no stable id; keying on the edited field steals focus
              <li key={index} className="flex items-center gap-2">
                <Input
                  value={option.label}
                  onChange={(e) => handleOptionChange(index, { label: e.target.value })}
                  placeholder={t("properties:picker.optionLabelPlaceholder")}
                  className="h-8 flex-1"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleOptionRemove(index)}
                  aria-label={t("properties:picker.removeOption")}
                >
                  <Plus className="h-4 w-4 rotate-45" />
                </Button>
              </li>
            ))}
          </ul>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            onClick={handleAddOption}
          >
            <Plus className="h-4 w-4" />
            {t("properties:picker.addOption")}
          </Button>
        </div>
      ) : null}

      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          className="flex-1"
          onClick={() => void handleCreate()}
          disabled={!canSubmit || createPropertyMutation.isPending}
        >
          {t("properties:picker.createButton")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onCancel}
          disabled={createPropertyMutation.isPending}
        >
          {t("common:cancel")}
        </Button>
      </div>
    </div>
  );
};

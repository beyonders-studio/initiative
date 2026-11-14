import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CounterSettingsInput,
  type CurrencyCode,
  MetadataType,
  type PropertyOption,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/ui/select";

import { CounterSettingsFields, counterSettingsValid } from "./CounterSettingsFields";
import { CurrencySelect, useDefaultCurrency } from "./CurrencySelect";
import {
  type MetadataOwner,
  normalizeOptionList,
  ownerColumns,
  type PropertyDefinition,
  typeRequiresOptions,
} from "./propertyHelpers";
import { iconForPropertyType } from "./propertyTypeIcons";

/** The types people define a property or metadata as, in the order they are
 *  offered. The rest of {@link MetadataType} are a plug-in's alone. */
export const PROPERTY_TYPES: MetadataType[] = [
  MetadataType.text,
  MetadataType.number,
  MetadataType.checkbox,
  MetadataType.date,
  MetadataType.datetime,
  MetadataType.url,
  MetadataType.select,
  MetadataType.multi_select,
  MetadataType.user_reference,
  MetadataType.currency,
  MetadataType.scale,
  MetadataType.counter,
  MetadataType.file,
  MetadataType.signature,
];

/** A property as it is made: an initiative's names the initiative, and
 *  metadata its project or collection. A plug-in's names neither. */
export interface NewProperty {
  name: string;
  type: MetadataType;
  options?: PropertyOption[] | null;
  currency?: CurrencyCode | null;
  counter?: CounterSettingsInput | null;
  initiative_id?: number;
  project_id?: number | null;
  collection_id?: number | null;
}

/** Makes a property, answering with it as made (`D`). A failure is told by
 *  this, and rejects. A method, whose parameter TypeScript checks both ways:
 *  one that makes only an initiative's is taken where an initiative is given. */
export type CreateProperty<D extends PropertyDefinition = PropertyDefinition> = {
  create(property: NewProperty): Promise<D>;
}["create"];

/**
 * A new property for an initiative, or metadata of one of its projects or
 * collections: its name, its type and, for a select, its options, for money
 * its currency, for a counter its step and bounds. Where an item's properties
 * are added to, and where a layout adds a field, it is the one way either is
 * made there.
 *
 * Given an `owner` that may also hold it, it asks whose it is: the owner's
 * metadata, or the initiative's property.
 */
export const NewPropertyForm = ({
  initiativeId,
  owner,
  create,
  name: startName = "",
  type: startType = MetadataType.text,
  onCreated,
  onCancel,
  onPendingChange,
}: {
  /** The initiative it is made in; none for a plug-in's own. */
  initiativeId?: number;
  /** The project or collection it may be metadata of; left out, it is the
   *  initiative's property. */
  owner?: MetadataOwner;
  create: CreateProperty;
  /** What the name starts as: what was searched for, say. */
  name?: string;
  /** The type it starts as. */
  type?: MetadataType;
  onCreated: (definition: PropertyDefinition) => void;
  onCancel: () => void;
  /** Told when creating starts and ends. */
  onPendingChange?: (pending: boolean) => void;
}) => {
  const { t } = useTranslation(["properties", "ui"]);
  const [newName, setNewName] = useState(startName);
  const [newType, setNewType] = useState<MetadataType>(startType);
  // An owner's metadata, until the initiative's property is asked for.
  const [owned, setOwned] = useState(owner !== undefined);
  const [newOptions, setNewOptions] = useState<PropertyOption[]>(() =>
    typeRequiresOptions(startType) ? [{ value: "", label: "" }] : []
  );
  const defaultCurrency = useDefaultCurrency();
  const [newCurrency, setNewCurrency] = useState<CurrencyCode>(defaultCurrency);
  const [newCounter, setNewCounter] = useState<CounterSettingsInput>({});
  const [pending, setPending] = useState(false);

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
    const payload: NewProperty = {
      name,
      type: newType,
      ...(initiativeId === undefined ? {} : { initiative_id: initiativeId }),
      ...ownerColumns(owned ? owner : undefined),
      options,
      ...(newType === MetadataType.currency ? { currency: newCurrency } : {}),
      ...(newType === MetadataType.counter ? { counter: newCounter } : {}),
    };
    setPending(true);
    onPendingChange?.(true);
    try {
      onCreated(await create(payload));
    } catch {
      // `create` tells of the failure.
    } finally {
      setPending(false);
      onPendingChange?.(false);
    }
  };

  const canSubmit = useMemo(() => {
    if (!newName.trim()) return false;
    if (typeRequiresOptions(newType)) {
      return normalizeOptionList(newOptions).length > 0;
    }
    if (newType === MetadataType.counter) return counterSettingsValid(newCounter);
    return true;
  }, [newName, newType, newOptions, newCounter]);

  return (
    <div className="space-y-3 p-3">
      <div className="font-medium text-sm">
        {t(owned ? "properties:picker.createPropertyHeading" : "properties:picker.createHeading")}
      </div>
      {owner !== undefined ? (
        <div className="space-y-2">
          <Label htmlFor="property-new-owner" className="font-normal text-xs">
            {t("properties:picker.ownerLabel")}
          </Label>
          <Select
            value={owned ? owner.kind : "initiative"}
            onValueChange={(value) => setOwned(value !== "initiative")}
          >
            <SelectTrigger id="property-new-owner">
              <span className="truncate">
                {t(`properties:picker.owner.${owned ? owner.kind : "initiative"}`)}
              </span>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={owner.kind}>
                {t(`properties:picker.owner.${owner.kind}`)}
              </SelectItem>
              <SelectItem value="initiative">{t("properties:picker.owner.initiative")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ) : null}
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
            const nextType = value as MetadataType;
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

      {newType === MetadataType.currency ? (
        <div className="space-y-2">
          <Label className="font-normal text-xs">{t("properties:currency.label")}</Label>
          <CurrencySelect value={newCurrency} onChange={setNewCurrency} />
        </div>
      ) : null}

      {newType === MetadataType.counter ? (
        <CounterSettingsFields value={newCounter} onChange={setNewCounter} />
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
          disabled={!canSubmit || pending}
        >
          {t("properties:picker.createButton")}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel} disabled={pending}>
          {t("ui:cancel")}
        </Button>
      </div>
    </div>
  );
};

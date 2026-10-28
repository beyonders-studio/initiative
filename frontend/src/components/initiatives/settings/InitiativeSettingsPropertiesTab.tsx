import { ArrowDown, ArrowUp, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CurrencyCode,
  MetadataType,
  type PropertyDefinitionCreate,
  type PropertyDefinitionRead,
  type PropertyDefinitionUpdate,
  type PropertyOption,
} from "@/api/generated/initiativeAPI.schemas";
import { CurrencySelect, useDefaultCurrency } from "@/components/properties/CurrencySelect";
import { PROPERTY_TYPES } from "@/components/properties/NewPropertyForm";
import { normalizeOptionList, typeRequiresOptions } from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type MetadataOwner,
  ownerColumns,
  useCreateProperty,
  useDeleteProperty,
  useProperties,
  useUpdateProperty,
} from "@/hooks/useProperties";
import { collator } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";

const DEFAULT_COLOR = "#64748B";

interface DialogState {
  mode: "create" | "edit";
  definition?: PropertyDefinitionRead;
}

interface FormState {
  name: string;
  type: MetadataType;
  color: string | null;
  options: PropertyOption[];
  /** A money property's currency. */
  currency: CurrencyCode;
}

const emptyFormState = (currency: CurrencyCode): FormState => ({
  name: "",
  type: MetadataType.text,
  color: null,
  options: [],
  currency,
});

const definitionToFormState = (
  definition: PropertyDefinitionRead,
  currency: CurrencyCode
): FormState => ({
  name: definition.name,
  type: definition.type,
  color: definition.color,
  currency: definition.currency ?? currency,
  options: (definition.options ?? []).map((option) => ({
    value: option.value,
    label: option.label,
    color: option.color ?? null,
  })),
});

/**
 * Sub-editor for select / multi_select option lists. Kept in-file because it
 * is only useful to the manager dialog — no other callers need it.
 */
interface OptionListEditorProps {
  options: PropertyOption[];
  onChange: (next: PropertyOption[]) => void;
  disabled?: boolean;
}

const OptionListEditor = ({ options, onChange, disabled }: OptionListEditorProps) => {
  const { t } = useTranslation(["properties", "common"]);

  const handleAdd = () => {
    onChange([...options, { value: "", label: "", color: null }]);
  };

  const handlePatch = (index: number, patch: Partial<PropertyOption>) => {
    onChange(options.map((option, i) => (i === index ? { ...option, ...patch } : option)));
  };

  const handleRemove = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {options.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("properties:picker.optionsRequired")}</p>
      ) : null}
      <ul className="space-y-2">
        {options.map((option, index) => (
          // Key by index, not by a field the user is editing: keying on
          // ``option.value``/``label`` remounts the input on every keystroke
          // and steals focus. The inputs are fully controlled by props and
          // rows only change via add/remove, so the index key is correct.
          // biome-ignore lint/suspicious/noArrayIndexKey: controlled rows with no stable id; keying on the edited field steals focus
          <li key={index} className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
            <Input
              value={option.label}
              onChange={(e) => handlePatch(index, { label: e.target.value })}
              placeholder={t("properties:manager.optionLabelPlaceholder")}
              className="h-9 flex-1"
              disabled={disabled}
            />
            <div className="w-24">
              <ColorPickerPopover
                value={option.color ?? DEFAULT_COLOR}
                onChangeComplete={(value) => handlePatch(index, { color: value })}
                disabled={disabled}
                triggerLabel={t("properties:manager.colorLabel")}
                className="h-9"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => handleRemove(index)}
              aria-label={t("properties:manager.removeOption")}
              disabled={disabled}
            >
              <X className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Button type="button" variant="outline" size="sm" onClick={handleAdd} disabled={disabled}>
        <Plus className="h-4 w-4" />
        {t("properties:manager.addOption")}
      </Button>
    </div>
  );
};

/** What the manager calls what it lists: an initiative's properties, or a
 *  project's or a collection's metadata. */
const WORDS = {
  initiative: {
    description: "properties:manager.description",
    create: "properties:manager.newDefinition",
    edit: "properties:manager.editDefinition",
    delete: "properties:manager.delete",
    deleteTitle: "properties:manager.deleteConfirmTitle",
    deleteBody: "properties:manager.deleteConfirmBody",
    none: "properties:noMetadata",
  },
  project: {
    description: "projects:properties.description",
    create: "projects:properties.create",
    edit: "projects:properties.edit",
    delete: "projects:properties.delete",
    deleteTitle: "projects:properties.deleteTitle",
    deleteBody: "projects:properties.deleteBody",
    none: "projects:properties.none",
  },
  collection: {
    description: "files:collections.properties.description",
    create: "files:collections.properties.create",
    edit: "files:collections.properties.edit",
    delete: "files:collections.properties.delete",
    deleteTitle: "files:collections.properties.deleteTitle",
    deleteBody: "files:collections.properties.deleteBody",
    none: "files:collections.properties.none",
  },
} as const;

/**
 * Initiative-manager surface for listing and managing custom property
 * definitions. The panel behind the Properties tab of an initiative's
 * settings, which is its own route (``/settings/properties``). Pairs with
 * ``PropertyFilter``/``PropertyList``/``PropertyInput`` which render
 * individual values on files and tasks.
 *
 * Given an ``owner``, it manages that project's or collection's properties
 * instead. Given a ``placement`` as well, it is the layout editor's: a narrow
 * list, each property with where it shows. Without ``canManage`` it lists
 * them and changes nothing.
 */
export const InitiativeSettingsPropertiesTab = ({
  initiativeId,
  owner,
  canManage = true,
  placement,
}: {
  initiativeId: number;
  owner?: MetadataOwner;
  canManage?: boolean;
  /** Where the property shows, said under its name. */
  placement?: (definition: PropertyDefinitionRead) => string;
}) => {
  const { t, i18n } = useTranslation(["properties", "common", "files", "projects"]);
  const words = WORDS[owner?.kind ?? "initiative"];
  const defaultCurrency = useDefaultCurrency();

  const propertiesQuery = useProperties(owner === undefined ? { initiativeId } : { owner });
  const createMutation = useCreateProperty();
  const updateMutation = useUpdateProperty();
  const deleteMutation = useDeleteProperty();

  const [dialogState, setDialogState] = useState<DialogState | null>(null);
  const [formState, setFormState] = useState<FormState>(() => emptyFormState(defaultCurrency));
  const [deleteTarget, setDeleteTarget] = useState<PropertyDefinitionRead | null>(null);
  const [moving, setMoving] = useState(false);

  const owned = owner !== undefined;
  const sortedDefinitions = useMemo(() => {
    // The initiative's own: none a project or a collection keeps.
    const list = (propertiesQuery.data ?? []).filter(
      (definition) => owned || (definition.project_id === null && definition.collection_id === null)
    );
    const byName = collator(i18n.language);
    return [...list].sort((a, b) => {
      if (a.position !== b.position) return a.position - b.position;
      return byName.compare(a.name, b.name);
    });
  }, [propertiesQuery.data, owned, i18n.language]);

  /** Move one a place up or down, numbering each in the order shown. */
  const move = async (index: number, by: -1 | 1) => {
    const order = [...sortedDefinitions];
    const [moved] = order.splice(index, 1);
    order.splice(index + by, 0, moved);
    setMoving(true);
    try {
      await Promise.all(
        order.flatMap((definition, position) =>
          definition.position === position
            ? []
            : [updateMutation.mutateAsync({ propertyId: definition.id, data: { position } })]
        )
      );
    } catch {
      // Error toast handled by the mutation hook.
    } finally {
      setMoving(false);
    }
  };

  // Sync the form state when the dialog target changes. Using an effect
  // here (rather than initializing via state) avoids stale form data when
  // the user closes one edit dialog and opens another without remounting.
  useEffect(() => {
    if (dialogState?.mode === "edit" && dialogState.definition) {
      setFormState(definitionToFormState(dialogState.definition, defaultCurrency));
    } else {
      setFormState(emptyFormState(defaultCurrency));
    }
  }, [dialogState, defaultCurrency]);

  const isEditing = dialogState?.mode === "edit";
  const submitting = createMutation.isPending || updateMutation.isPending;

  const handleOpenCreate = () => setDialogState({ mode: "create" });
  const handleOpenEdit = (definition: PropertyDefinitionRead) =>
    setDialogState({ mode: "edit", definition });
  const handleCloseDialog = () => setDialogState(null);

  const handleTypeChange = (nextType: MetadataType) => {
    setFormState((prev) => {
      // When switching into a select-style type, seed with a single empty
      // option so the editor renders a row to fill in. Switching away clears
      // any options so they don't silently linger on the payload.
      if (typeRequiresOptions(nextType) && prev.options.length === 0) {
        return { ...prev, type: nextType, options: [{ value: "", label: "", color: null }] };
      }
      if (!typeRequiresOptions(nextType)) {
        return { ...prev, type: nextType, options: [] };
      }
      return { ...prev, type: nextType };
    });
  };

  const canSubmit = useMemo(() => {
    if (!formState.name.trim()) return false;
    if (typeRequiresOptions(formState.type)) {
      return normalizeOptionList(formState.options).length > 0;
    }
    return true;
  }, [formState]);

  const handleSubmit = async () => {
    if (!canSubmit || !dialogState) return;

    const trimmedName = formState.name.trim();
    const options = typeRequiresOptions(formState.type)
      ? normalizeOptionList(formState.options)
      : undefined;

    if (dialogState.mode === "create") {
      const payload: PropertyDefinitionCreate = {
        name: trimmedName,
        type: formState.type,
        initiative_id: initiativeId,
        ...ownerColumns(owner),
        color: formState.color ?? null,
        options,
        ...(formState.type === MetadataType.currency ? { currency: formState.currency } : {}),
        // A new one goes last.
        position: sortedDefinitions.length,
      };
      try {
        await createMutation.mutateAsync(payload);
        toast.success(t(words.create));
        handleCloseDialog();
      } catch {
        // Error toast handled by the mutation hook.
      }
      return;
    }

    if (!dialogState.definition) return;
    const payload: PropertyDefinitionUpdate = {
      name: trimmedName,
      color: formState.color ?? null,
      // Type is immutable on edit, so use the existing definition's type to
      // decide whether to include options in the PATCH payload.
      options: typeRequiresOptions(dialogState.definition.type) ? options : undefined,
      currency:
        dialogState.definition.type === MetadataType.currency ? formState.currency : undefined,
    };
    try {
      const response = await updateMutation.mutateAsync({
        propertyId: dialogState.definition.id,
        data: payload,
      });
      if (response.orphaned_value_count > 0) {
        toast.warning(
          t("properties:manager.orphanedWarning", {
            count: response.orphaned_value_count,
          })
        );
      } else {
        toast.success(t(words.edit));
      }
      handleCloseDialog();
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success(t(words.delete));
      setDeleteTarget(null);
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  /** Moving it up or down, editing it and deleting it. */
  const rowActions = (definition: PropertyDefinitionRead, index: number) => (
    <div className="inline-flex shrink-0 items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={() => void move(index, -1)}
        disabled={moving || index === 0}
        aria-label={t("properties:manager.moveUp", { name: definition.name })}
      >
        <ArrowUp className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={() => void move(index, 1)}
        disabled={moving || index === sortedDefinitions.length - 1}
        aria-label={t("properties:manager.moveDown", { name: definition.name })}
      >
        <ArrowDown className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={() => handleOpenEdit(definition)}
        aria-label={t(words.edit)}
      >
        <Pencil className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={() => setDeleteTarget(definition)}
        aria-label={t(words.delete)}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );

  const newButton = canManage ? (
    <Button onClick={handleOpenCreate}>
      <Plus className="h-4 w-4" />
      {t(words.create)}
    </Button>
  ) : null;
  const list: ReactNode = propertiesQuery.isLoading ? (
    <div className="flex items-center gap-2 text-muted-foreground text-sm">
      <Loader2 className="h-4 w-4 animate-spin" />
      {t("common:loading")}
    </div>
  ) : sortedDefinitions.length === 0 ? (
    <p className="text-muted-foreground text-sm">{t(words.none)}</p>
  ) : placement ? (
    <ul className="divide-y rounded-md border text-sm">
      {sortedDefinitions.map((definition, index) => {
        const Icon = iconForPropertyType(definition.type);
        return (
          <li key={definition.id} className="space-y-1 px-3 py-2">
            <div className="flex items-center gap-2">
              <Icon
                className="h-4 w-4 shrink-0 text-muted-foreground"
                aria-label={t(`properties:types.${definition.type}`)}
                role="img"
              />
              <span className="min-w-0 flex-1 truncate font-medium">{definition.name}</span>
              {canManage ? rowActions(definition, index) : null}
            </div>
            <p className="text-muted-foreground text-xs">{placement(definition)}</p>
          </li>
        );
      })}
    </ul>
  ) : (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("properties:manager.nameLabel")}</TableHead>
            <TableHead>{t("properties:manager.typeLabel")}</TableHead>
            <TableHead>{t("properties:manager.optionsLabel")}</TableHead>
            <TableHead>{t("properties:manager.colorLabel")}</TableHead>
            {canManage ? <TableHead className="w-40 text-right" /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedDefinitions.map((definition, index) => {
            const optionCount = definition.options?.length ?? 0;
            const Icon = iconForPropertyType(definition.type);
            return (
              <TableRow key={definition.id}>
                <TableCell className="font-medium">{definition.name}</TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    <span>{t(`properties:types.${definition.type}`)}</span>
                    {definition.currency ? (
                      <span className="text-muted-foreground text-xs">{definition.currency}</span>
                    ) : null}
                  </span>
                </TableCell>
                <TableCell>{optionCount > 0 ? optionCount : "—"}</TableCell>
                <TableCell>
                  {definition.color ? (
                    <span className="inline-flex items-center gap-2">
                      <span
                        aria-hidden
                        className="inline-block h-4 w-4 rounded-full border"
                        style={{ backgroundColor: definition.color }}
                      />
                      <span className="font-mono text-muted-foreground text-xs uppercase">
                        {definition.color}
                      </span>
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                {canManage ? (
                  <TableCell className="text-right">{rowActions(definition, index)}</TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* In the layout editor it is a panel of its own, which is the frame a
          card would be. */}
      {placement === undefined ? (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardDescription>{t(words.description)}</CardDescription>
            </div>
            {newButton}
          </CardHeader>
          <CardContent>{list}</CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">{t(words.description)}</p>
          {list}
          {canManage ? (
            <Button type="button" variant="outline" size="sm" onClick={handleOpenCreate}>
              <Plus className="h-4 w-4" />
              {t(words.create)}
            </Button>
          ) : null}
        </div>
      )}

      <Dialog
        open={dialogState !== null}
        onOpenChange={(next) => {
          if (!next) handleCloseDialog();
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{isEditing ? t(words.edit) : t(words.create)}</DialogTitle>
            <DialogDescription>{t(words.description)}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="property-manager-name">{t("properties:manager.nameLabel")}</Label>
              <Input
                id="property-manager-name"
                value={formState.name}
                onChange={(e) => setFormState((prev) => ({ ...prev, name: e.target.value }))}
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="property-manager-type">{t("properties:manager.typeLabel")}</Label>
              <Select
                value={formState.type}
                onValueChange={(next) => handleTypeChange(next as MetadataType)}
                disabled={isEditing}
              >
                <SelectTrigger id="property-manager-type">
                  <div className="flex min-w-0 items-center gap-2">
                    {(() => {
                      const Icon = iconForPropertyType(formState.type);
                      return <Icon className="h-4 w-4 shrink-0" />;
                    })()}
                    <span className="truncate">{t(`properties:types.${formState.type}`)}</span>
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {PROPERTY_TYPES.map((type) => {
                    const Icon = iconForPropertyType(type);
                    const label = t(`properties:types.${type}`);
                    return (
                      <SelectItem key={type} value={type} textValue={label}>
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

            {formState.type === MetadataType.currency ? (
              <div className="space-y-2">
                <Label>{t("properties:currency.label")}</Label>
                <CurrencySelect
                  value={formState.currency}
                  onChange={(currency) => setFormState((prev) => ({ ...prev, currency }))}
                />
              </div>
            ) : null}

            <div className="space-y-2">
              <Label>{t("properties:manager.colorLabel")}</Label>
              <ColorPickerPopover
                value={formState.color ?? DEFAULT_COLOR}
                onChangeComplete={(value) => setFormState((prev) => ({ ...prev, color: value }))}
              />
            </div>

            {typeRequiresOptions(formState.type) ? (
              <div className="space-y-2">
                <Label>{t("properties:manager.optionsLabel")}</Label>
                <OptionListEditor
                  options={formState.options}
                  onChange={(next) => setFormState((prev) => ({ ...prev, options: next }))}
                />
              </div>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleCloseDialog}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit || submitting}
            >
              {submitting ? t("common:submitting") : t("common:save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null);
        }}
        title={t(words.deleteTitle)}
        description={t(words.deleteBody)}
        confirmLabel={t(words.delete)}
        cancelLabel={t("common:cancel")}
        onConfirm={() => void handleConfirmDelete()}
        isLoading={deleteMutation.isPending}
        destructive
      />
    </div>
  );
};

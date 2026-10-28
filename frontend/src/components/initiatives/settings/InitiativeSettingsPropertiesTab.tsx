import { ArrowDown, ArrowUp, ArrowUpToLine, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CurrencyCode,
  MetadataType,
  type PropertyDefinitionCreate,
  type PropertyDefinitionGroup,
  type PropertyDefinitionRead,
  type PropertyDefinitionUpdate,
  type PropertyOption,
} from "@/api/generated/initiativeAPI.schemas";
import { CurrencySelect, useDefaultCurrency } from "@/components/properties/CurrencySelect";
import { PROPERTY_TYPES } from "@/components/properties/NewPropertyForm";
import { normalizeOptionList, typeRequiresOptions } from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
  useCreateProperty,
  useDeleteProperties,
  useDeleteProperty,
  usePromoteProperties,
  usePropertyGroups,
  useUpdateProperty,
} from "@/hooks/useProperties";
import { toast } from "@/lib/mascotToast";

const DEFAULT_COLOR = "#64748B";

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
 * is only useful to the property dialog — no other callers need it.
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

/** What a definition is called by its owner: the initiative's metadata, or a
 *  project's or a collection's property. */
const WORDS = {
  initiative: {
    description: "properties:manager.description",
    edit: "properties:manager.editDefinition",
    delete: "properties:manager.delete",
    deleteTitle: "properties:manager.deleteConfirmTitle",
    deleteBody: "properties:manager.deleteConfirmBody",
  },
  project: {
    description: "projects:properties.description",
    edit: "projects:properties.edit",
    delete: "projects:properties.delete",
    deleteTitle: "projects:properties.deleteTitle",
    deleteBody: "projects:properties.deleteBody",
  },
  collection: {
    description: "files:collections.properties.description",
    edit: "files:collections.properties.edit",
    delete: "files:collections.properties.delete",
    deleteTitle: "files:collections.properties.deleteTitle",
    deleteBody: "files:collections.properties.deleteBody",
  },
} as const;

/** The words for `definition`, by whose it is; none is new metadata. */
export const propertyWords = (definition?: PropertyDefinitionRead | null) =>
  WORDS[
    definition?.project_id != null
      ? "project"
      : definition?.collection_id != null
        ? "collection"
        : "initiative"
  ];

const PROPERTY_NAMESPACES = ["properties", "common", "files", "projects"] as const;

/**
 * A definition's name, options and their colors, color and currency, saved
 * as one change; or, given no `definition`, new metadata of the initiative's,
 * whose type is chosen then and kept. Where one is edited: the initiative's
 * settings, and the layout editor, from the field that shows it.
 */
export const PropertyDialog = ({
  open,
  definition,
  initiativeId,
  position = 0,
  onClose,
}: {
  open: boolean;
  /** The one to edit; left out, new metadata of the initiative's. */
  definition?: PropertyDefinitionRead;
  initiativeId: number;
  /** Where new metadata goes among the initiative's. */
  position?: number;
  onClose: () => void;
}) => {
  const { t } = useTranslation(PROPERTY_NAMESPACES);
  const words = propertyWords(definition);
  const defaultCurrency = useDefaultCurrency();
  const createMutation = useCreateProperty();
  const updateMutation = useUpdateProperty();
  const [formState, setFormState] = useState<FormState>(() => emptyFormState(defaultCurrency));

  // Sync the form when the dialog opens, so one closed and another opened
  // without remounting starts from what the new one holds.
  useEffect(() => {
    if (!open) return;
    setFormState(
      definition
        ? definitionToFormState(definition, defaultCurrency)
        : emptyFormState(defaultCurrency)
    );
  }, [open, definition, defaultCurrency]);

  const isEditing = definition !== undefined;
  const title = isEditing ? words.edit : "properties:manager.newDefinition";
  const submitting = createMutation.isPending || updateMutation.isPending;

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
    if (!canSubmit) return;

    const trimmedName = formState.name.trim();
    const options = typeRequiresOptions(formState.type)
      ? normalizeOptionList(formState.options)
      : undefined;

    if (!definition) {
      const payload: PropertyDefinitionCreate = {
        name: trimmedName,
        type: formState.type,
        initiative_id: initiativeId,
        color: formState.color ?? null,
        options,
        ...(formState.type === MetadataType.currency ? { currency: formState.currency } : {}),
        position,
      };
      try {
        await createMutation.mutateAsync(payload);
        toast.success(t(title));
        onClose();
      } catch {
        // Error toast handled by the mutation hook.
      }
      return;
    }

    const payload: PropertyDefinitionUpdate = {
      name: trimmedName,
      color: formState.color ?? null,
      // Type is immutable on edit, so use the existing definition's type to
      // decide whether to include options in the PATCH payload.
      options: typeRequiresOptions(definition.type) ? options : undefined,
      currency: definition.type === MetadataType.currency ? formState.currency : undefined,
    };
    try {
      const response = await updateMutation.mutateAsync({
        propertyId: definition.id,
        data: payload,
      });
      if (response.orphaned_value_count > 0) {
        toast.warning(
          t("properties:manager.orphanedWarning", {
            count: response.orphaned_value_count,
          })
        );
      } else {
        toast.success(t(title));
      }
      onClose();
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(title)}</DialogTitle>
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
          <Button type="button" variant="outline" onClick={onClose}>
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
  );
};

/** Deleting `definition`, with every value of it, once asked; closed while
 *  none is given. */
export const PropertyDeleteDialog = ({
  definition,
  onClose,
}: {
  definition: PropertyDefinitionRead | null;
  onClose: () => void;
}) => {
  const { t } = useTranslation(PROPERTY_NAMESPACES);
  const words = propertyWords(definition);
  const deleteMutation = useDeleteProperty();
  const handleConfirm = async () => {
    if (!definition) return;
    try {
      await deleteMutation.mutateAsync(definition.id);
      toast.success(t(words.delete));
      onClose();
    } catch {
      // Error toast handled by the mutation hook.
    }
  };
  return (
    <ConfirmDialog
      open={definition !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={t(words.deleteTitle)}
      description={t(words.deleteBody)}
      confirmLabel={t(words.delete)}
      cancelLabel={t("common:cancel")}
      onConfirm={() => void handleConfirm()}
      isLoading={deleteMutation.isPending}
      destructive
    />
  );
};

/**
 * Merging the properties selected into one of the initiative's metadata,
 * under a name: the metadata of that name and type if there is one, otherwise
 * a new one.
 */
const PromoteDialog = ({
  open,
  initiativeId,
  sources,
  metadata,
  onClose,
  onPromoted,
}: {
  open: boolean;
  initiativeId: number;
  sources: PropertyDefinitionRead[];
  /** The initiative's metadata, one of which a name may already be. */
  metadata: PropertyDefinitionRead[];
  onClose: () => void;
  onPromoted: () => void;
}) => {
  const { t } = useTranslation(PROPERTY_NAMESPACES);
  const promote = usePromoteProperties();
  const [name, setName] = useState("");
  const first = sources[0];
  useEffect(() => {
    if (open) setName(first?.name ?? "");
  }, [open, first]);
  const trimmed = name.trim();
  const same = metadata.find(
    (definition) => definition.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase()
  );
  const fits =
    same === undefined || (same.type === first?.type && same.currency === first?.currency);

  const handleSubmit = async () => {
    try {
      await promote.mutateAsync({
        initiative_id: initiativeId,
        ids: sources.map((source) => source.id),
        name: trimmed,
      });
      toast.success(t("properties:manager.promoted", { name: trimmed }));
      onPromoted();
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("properties:manager.promote")}</DialogTitle>
          <DialogDescription>
            {t("properties:manager.promoteBody", { count: sources.length })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="promote-name">{t("properties:manager.nameLabel")}</Label>
          <Input
            id="promote-name"
            value={name}
            maxLength={100}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
          {same !== undefined ? (
            <p className={fits ? "text-muted-foreground text-sm" : "text-destructive text-sm"}>
              {fits
                ? t("properties:manager.promoteInto", { name: same.name })
                : t("properties:manager.promoteTaken")}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common:cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!trimmed || !fits || promote.isPending}
          >
            {promote.isPending ? t("common:submitting") : t("properties:manager.promote")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/** Whether `definition` is a project's or a collection's property. */
const isToolProperty = (definition: PropertyDefinitionRead) =>
  definition.project_id !== null || definition.collection_id !== null;

/**
 * Initiative settings › Metadata: the initiative's metadata, then each of its
 * projects' and collections' properties under the owner's name. It lists what
 * the server lists, which is only the properties of the tools the reader may
 * edit, and offers what each group's `can_edit` allows: editing one,
 * reordering, deleting several at once, and promoting properties of one type
 * into one of the initiative's metadata. A project's or a collection's
 * properties are made in its layout editor; the initiative's metadata here.
 */
export const InitiativeSettingsPropertiesTab = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation(PROPERTY_NAMESPACES);
  const groupsQuery = usePropertyGroups(initiativeId);
  const updateMutation = useUpdateProperty();
  const deleteMany = useDeleteProperties();

  const [editing, setEditing] = useState<{ definition?: PropertyDefinitionRead } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PropertyDefinitionRead | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [askingDelete, setAskingDelete] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [moving, setMoving] = useState(false);

  const groups = groupsQuery.data?.groups ?? [];
  const metadataGroup = groups.find((group) => group.owner === "initiative");
  const toolGroups = groups.filter((group) => group.owner !== "initiative");
  // What is selected, of what is still listed.
  const chosen = groups.flatMap((group) =>
    group.definitions.filter((definition) => selected.has(definition.id))
  );
  const promotable =
    chosen.length > 0 &&
    chosen.every(
      (definition) =>
        isToolProperty(definition) &&
        definition.type === chosen[0].type &&
        definition.currency === chosen[0].currency
    );

  const toggle = (id: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  /** Move one of a group's a place up or down, numbering each in the order
   *  shown. */
  const move = async (definitions: PropertyDefinitionRead[], index: number, by: -1 | 1) => {
    const order = [...definitions];
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

  const handleDeleteSelected = async () => {
    try {
      await deleteMany.mutateAsync({
        initiative_id: initiativeId,
        ids: chosen.map((definition) => definition.id),
      });
      toast.success(t("properties:manager.bulkDeleted", { count: chosen.length }));
      setSelected(new Set());
      setAskingDelete(false);
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  const table = ({ definitions, can_edit: canEdit }: PropertyDefinitionGroup) => (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {canEdit ? <TableHead className="w-10" /> : null}
            <TableHead>{t("properties:manager.nameLabel")}</TableHead>
            <TableHead>{t("properties:manager.typeLabel")}</TableHead>
            <TableHead>{t("properties:manager.optionsLabel")}</TableHead>
            <TableHead>{t("properties:manager.colorLabel")}</TableHead>
            {canEdit ? <TableHead className="w-40 text-right" /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {definitions.map((definition, index) => {
            const optionCount = definition.options?.length ?? 0;
            const Icon = iconForPropertyType(definition.type);
            const words = propertyWords(definition);
            return (
              <TableRow key={definition.id}>
                {canEdit ? (
                  <TableCell>
                    <Checkbox
                      checked={selected.has(definition.id)}
                      onCheckedChange={(checked) => toggle(definition.id, checked === true)}
                      aria-label={t("properties:manager.select", { name: definition.name })}
                    />
                  </TableCell>
                ) : null}
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
                {canEdit ? (
                  <TableCell className="text-right">
                    <div className="inline-flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => void move(definitions, index, -1)}
                        disabled={moving || index === 0}
                        aria-label={t("properties:manager.moveUp", { name: definition.name })}
                      >
                        <ArrowUp className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => void move(definitions, index, 1)}
                        disabled={moving || index === definitions.length - 1}
                        aria-label={t("properties:manager.moveDown", { name: definition.name })}
                      >
                        <ArrowDown className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditing({ definition })}
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
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );

  if (groupsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {chosen.length > 0 ? (
        <div
          role="toolbar"
          aria-label={t("properties:manager.selected", { count: chosen.length })}
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 p-2"
        >
          <span className="px-1 font-medium text-sm">
            {t("properties:manager.selected", { count: chosen.length })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!promotable}
            onClick={() => setPromoting(true)}
          >
            <ArrowUpToLine className="h-4 w-4" />
            {t("properties:manager.promote")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => setAskingDelete(true)}
          >
            <Trash2 className="h-4 w-4" />
            {t("common:delete")}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            {t("common:clear")}
          </Button>
          {!promotable ? (
            <p className="basis-full px-1 text-muted-foreground text-xs">
              {t("properties:manager.promoteHint")}
            </p>
          ) : null}
        </div>
      ) : null}

      {metadataGroup ? (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4">
            <CardDescription>{t("properties:manager.description")}</CardDescription>
            {metadataGroup.can_edit ? (
              <Button onClick={() => setEditing({})}>
                <Plus className="h-4 w-4" />
                {t("properties:manager.newDefinition")}
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {metadataGroup.definitions.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("properties:noMetadata")}</p>
            ) : (
              table(metadataGroup)
            )}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("properties:manager.toolsTitle")}</CardTitle>
          <CardDescription>{t("properties:manager.toolsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {toolGroups.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("properties:manager.noTools")}</p>
          ) : (
            toolGroups.map((group) => (
              <section
                key={`${group.owner}:${group.owner_id}`}
                aria-label={group.name ?? undefined}
                className="space-y-2"
              >
                <h3 className="flex flex-wrap items-center gap-2 font-medium text-sm">
                  {group.name}
                  <Badge variant="secondary">
                    {t(`properties:manager.owner.${group.owner as "project" | "collection"}`)}
                  </Badge>
                </h3>
                {table(group)}
              </section>
            ))
          )}
        </CardContent>
      </Card>

      <PropertyDialog
        open={editing !== null}
        definition={editing?.definition}
        initiativeId={initiativeId}
        position={metadataGroup?.definitions.length ?? 0}
        onClose={() => setEditing(null)}
      />
      <PropertyDeleteDialog definition={deleteTarget} onClose={() => setDeleteTarget(null)} />
      <ConfirmDialog
        open={askingDelete}
        onOpenChange={setAskingDelete}
        title={t("properties:manager.bulkDeleteTitle", { count: chosen.length })}
        description={t("properties:manager.bulkDeleteBody")}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => void handleDeleteSelected()}
        isLoading={deleteMany.isPending}
        destructive
      />
      <PromoteDialog
        open={promoting}
        initiativeId={initiativeId}
        sources={promotable ? chosen : []}
        metadata={metadataGroup?.definitions ?? []}
        onClose={() => setPromoting(false)}
        onPromoted={() => {
          setPromoting(false);
          setSelected(new Set());
        }}
      />
    </div>
  );
};

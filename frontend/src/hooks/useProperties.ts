import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { setCollectionFileMetadata } from "@/api/generated/files/files";
import type {
  PropertyDefinitionBulkDelete,
  PropertyDefinitionCreate,
  PropertyDefinitionPromote,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyOption,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget } from "@/api/generated/initiativeAPI.schemas";
import { setProperties } from "@/api/generated/properties/properties";
import {
  createPropertyDefinition,
  deletePropertyDefinition,
  deletePropertyDefinitions,
  promotePropertyDefinitions,
  updatePropertyDefinition,
  useListPropertyDefinitions,
  useListPropertyDefinitionsByOwner,
} from "@/api/generated/property-definitions/property-definitions";
import { invalidate, q } from "@/api/query-keys";
import {
  buildUniqueOptionSlug,
  findOptionByLabel,
  type MetadataOwner,
  ownerColumns,
} from "@/components/properties/propertyHelpers";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { type FieldSaveKind, heldKey } from "@/hooks/useFieldSave";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ──────────────────────────────────────────────────────────────────

/**
 * List property definitions.
 *
 * - ``initiativeId`` bound: scopes to that one initiative (for per-entity
 *   pickers and the initiative settings manager page).
 * - ``initiativeId`` omitted: returns the union across every initiative the
 *   caller is a member of — used by global views (My Tasks, Files list,
 *   events list) so property columns and filters aggregate across initiatives.
 * - ``owner`` bound: that project's or collection's metadata instead, which
 *   are never among an initiative's properties.
 */
export const useProperties = (options?: {
  initiativeId?: number;
  owner?: MetadataOwner;
  enabled?: boolean;
}) => {
  const communityId = useActiveCommunityId();
  const initiativeId = options?.initiativeId;
  const params: { initiative_id?: number; project_id?: number; collection_id?: number } = {
    ...ownerColumns(options?.owner),
  };
  if (initiativeId !== undefined) params.initiative_id = initiativeId;
  const hasParams = Object.keys(params).length > 0;
  return useListPropertyDefinitions(communityId, hasParams ? params : undefined, {
    query: { enabled: options?.enabled ?? true, staleTime: 60 * 1000 },
  });
};

/**
 * An initiative's metadata, then the properties of each of its projects and
 * collections the reader may edit, each under its owner: what the server
 * lists, and only that.
 */
export const usePropertyGroups = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId };
  return useListPropertyDefinitionsByOwner(communityId, params, {
    query: { staleTime: 60 * 1000 },
  });
};

/** No definitions, as one list, for a read not yet answered. */
export const NO_DEFINITIONS: PropertyDefinitionRead[] = [];

/**
 * What can be placed on an item where an owner keeps metadata beside the
 * initiative's properties: the owner's metadata first, then the properties.
 * Without an owner, the properties alone.
 */
export const useOwnedDefinitions = (options: {
  initiativeId?: number;
  owner?: MetadataOwner;
  enabled?: boolean;
}) => {
  const enabled = options.enabled ?? true;
  const owned = options.owner !== undefined;
  const properties = useProperties({ initiativeId: options.initiativeId, enabled });
  const metadata = useProperties({
    owner: options.owner,
    enabled: enabled && owned,
  });
  const data = useMemo(
    () =>
      properties.data && (!owned || metadata.data)
        ? [...(owned ? (metadata.data ?? []) : []), ...properties.data]
        : undefined,
    [properties.data, metadata.data, owned]
  );
  return {
    data,
    isLoading: properties.isLoading || (owned && metadata.isLoading),
    isError: properties.isError || (owned && metadata.isError),
    refetch: () => Promise.all([properties.refetch(), metadata.refetch()]),
  };
};

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateProperty = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionCreate>
) =>
  useCommunityMutation<PropertyDefinitionRead, PropertyDefinitionCreate>(
    {
      mutationFn: (communityId, data) => createPropertyDefinition(communityId, data),
      // A collection's metadata is listed with the collection, and its lists.
      invalidate: (created) =>
        invalidate(q.allProperties(), ...(created.collection_id ? [q.allCollections()] : [])),
      errorKey: "properties:manager.createError",
    },
    options
  );

export const useUpdateProperty = (
  options?: MutationOpts<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >
) =>
  useCommunityMutation<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >(
    {
      mutationFn: (communityId, { propertyId, data }) =>
        updatePropertyDefinition(communityId, propertyId, data),
      // Every row's embedded summaries carry the definition's name, options
      // and color, as a collection's files carry its metadata's.
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders(), q.allCollections()),
      errorKey: "properties:manager.updateError",
    },
    options
  );

export const useDeleteProperty = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, propertyId) => deletePropertyDefinition(communityId, propertyId),
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders(), q.allCollections()),
      errorKey: "properties:manager.deleteError",
    },
    options
  );

/** Delete several definitions of one initiative at once, or none. */
export const useDeleteProperties = (options?: MutationOpts<void, PropertyDefinitionBulkDelete>) =>
  useCommunityMutation<void, PropertyDefinitionBulkDelete>(
    {
      mutationFn: (communityId, data) => deletePropertyDefinitions(communityId, data),
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders(), q.allCollections()),
      errorKey: "properties:manager.bulkDeleteError",
    },
    options
  );

/** Merge properties of one type into one of the initiative's metadata. Their
 *  values and the layouts that show them move with them. */
export const usePromoteProperties = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionPromote>
) =>
  useCommunityMutation<PropertyDefinitionRead, PropertyDefinitionPromote>(
    {
      mutationFn: (communityId, data) => promotePropertyDefinitions(communityId, data),
      invalidate: () =>
        invalidate(q.allProperties(), q.allPropertyHolders(), q.allCollections(), q.layouts()),
      errorKey: "properties:manager.promoteError",
    },
    options
  );

/**
 * Append a single option to a select / multi_select definition and return
 * the newly-added option. If a case-insensitive label match already exists
 * the existing option is returned without hitting the network, so the UI
 * can use it transparently as "picked" after the user typed an existing
 * label. A failure is toasted here, and rejects.
 */
export const useAppendPropertyOption = () => {
  const { t } = useTranslation("properties");
  const mutation = useCommunityMutation({
    mutationFn: async (
      communityId: number,
      vars: { definition: { id: number; options: PropertyOption[] }; label: string }
    ) => {
      const label = vars.label.trim();
      if (!label) {
        throw new Error("Option label cannot be empty");
      }
      const existing = findOptionByLabel(vars.definition, label);
      if (existing) {
        return { option: existing, created: false as const };
      }
      const currentOptions = vars.definition.options;
      const slug = buildUniqueOptionSlug(label, currentOptions);
      const nextOptions: PropertyOption[] = [
        ...currentOptions,
        { value: slug, label, color: null },
      ];
      const saved = await updatePropertyDefinition(communityId, vars.definition.id, {
        options: nextOptions,
      });
      // The server keeps options it already holds as they are, so the one
      // asked for is only there if it came back under this label.
      const stored = findOptionByLabel(saved.definition, label);
      if (!stored) {
        void invalidate(q.allProperties());
        throw new Error("Option was not added");
      }
      return { option: stored, created: true as const };
    },
    invalidate: (result) => {
      void invalidate(q.allProperties(), q.allPropertyHolders());
      if (result.created) {
        toast.success(t("input.optionAdded"));
      }
    },
    errorKey: "properties:input.optionAddFailed",
  });

  return (definition: { id: number; options: PropertyOption[] }, label: string) =>
    mutation.mutateAsync({ definition, label }).then(({ option }) => option);
};

/** Anything that carries property values. */
type PropertyHolder = { properties: PropertySummary[] };

/**
 * How each kind of row's properties are saved, one value at a time, where the
 * page holds no read of the row to write answers into: they are held where
 * {@link useHeldItem} reads them.
 */
export const propertySaves = Object.fromEntries(
  Object.values(PropertyTarget).map(
    (target): [PropertyTarget, FieldSaveKind<PropertyHolder, never>] => [
      target,
      {
        name: `properties-${target}`,
        readKey: (communityId, id) => heldKey(`properties-${target}`, communityId, id),
        // Only its properties are saved this way.
        patch: () => Promise.reject(new Error("a row's properties take no patch")),
        properties: target,
        lists: () => q.propertyHolder(target),
        itself: () => ({}),
      },
    ]
  )
) as Record<PropertyTarget, FieldSaveKind<PropertyHolder, never>>;

/** A counter on an item a list shows, stepped up or down. */
export type CounterStep = { itemId: number; definition: PropertyDefinitionRead; up: boolean };

/**
 * Steps counters on the `target`s a list shows, each from what it holds when
 * the step lands, and has the reads showing it read it again. A collection's
 * metadata is the collection's, so it is stepped through the collection.
 * Answers the item's values as the server then holds them.
 */
export const useStepCounter = (target: PropertyTarget) =>
  useCommunityMutation<PropertySummary[], CounterStep>({
    mutationFn: (communityId, { itemId, definition, up }) => {
      const body = { merge: true, steps: [{ property_id: definition.id, up }] };
      return definition.collection_id === null
        ? setProperties(communityId, target, itemId, body)
        : setCollectionFileMetadata(communityId, definition.collection_id, itemId, body);
    },
    invalidate: () =>
      invalidate(
        q.propertyHolder(target),
        ...(target === PropertyTarget.file ? [q.allCollections()] : [])
      ),
    errorKey: "properties:manager.setValuesError",
  });

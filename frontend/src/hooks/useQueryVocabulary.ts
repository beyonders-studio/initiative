/**
 * The words a statement may contain, and the fields behind each of them.
 *
 * Both halves come from the server's own registry — the datasets and functions
 * from the validator's allow-lists, the fields from the field registry — so a
 * name offered while somebody types is one the validator accepts. Neither
 * describes anybody's rows, and the datasets are the community's tool set's: the
 * answer changes only when an install does, so both are cached until then
 * (`q.plugins()` reaches them) and every consumer in a community shares one
 * request.
 */

import { useQueries } from "@tanstack/react-query";

import {
  getReadFieldCatalogQueryOptions,
  useReadQueryVocabulary,
} from "@/api/generated/fields/fields";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { DatasetFields } from "@/lib/widgets/completion";

/** Neither answer changes until the community's installs do. */
const FOREVER = {
  staleTime: Number.POSITIVE_INFINITY,
  gcTime: Number.POSITIVE_INFINITY,
} as const;

const NO_DATASETS: string[] = [];
const NO_FUNCTIONS: string[] = [];
const NO_TOKENS: string[] = [];
const NO_FIELDS: DatasetFields[] = [];

/** What a statement may name and call. */
export const useQueryVocabulary = (enabled = true) => {
  const communityId = useActiveCommunityId();
  const query = useReadQueryVocabulary(communityId, { query: { enabled, ...FOREVER } });
  return {
    datasets: query.data?.datasets ?? NO_DATASETS,
    functions: query.data?.functions ?? NO_FUNCTIONS,
    tokens: query.data?.tokens ?? NO_TOKENS,
    isLoading: query.isLoading,
  };
};

/**
 * The fields of several datasets at once.
 *
 * One query each rather than one call for all of them, so a dataset already
 * read for a filter control or the builder is not read again — the cache key is
 * the endpoint's own, so every consumer of a dataset shares the one request.
 */
export const useFieldCatalogs = (datasets: string[], enabled = true): DatasetFields[] => {
  const communityId = useActiveCommunityId();
  return useQueries({
    queries: datasets.map((dataset) =>
      getReadFieldCatalogQueryOptions(communityId, dataset, { query: { enabled, ...FOREVER } })
    ),
    // Reduced here rather than after the hook returns, so the array is stable
    // between renders and the completion list is not rebuilt on every keystroke.
    combine: (results) => {
      const answered = results
        .map((result) => result.data)
        .filter((data): data is NonNullable<typeof data> => Boolean(data))
        .map(
          (data): DatasetFields => ({
            dataset: data.dataset,
            fields: data.fields.map((field) => ({ name: field.name, type: field.type })),
            // What each dataset can be read alongside, so a name written under
            // a relation completes against what that relation reaches.
            relations: (data.relations ?? []).map((relation) => ({
              name: relation.name,
              dataset: relation.dataset,
            })),
          })
        );
      return answered.length ? answered : NO_FIELDS;
    },
  });
};

/**
 * The fields a dataset offers, from the server's field registry.
 *
 * There is one declaration of what a field is — its type, the operators it
 * accepts, the control that picks a value — and it lives on the backend beside
 * the engine that compiles filters. This reads it, so a control can never offer
 * an operator the server would refuse and a new field reaches the UI without a
 * second list being edited.
 *
 * The answer describes a dataset's shape rather than anybody's rows, and the
 * datasets are the community's tool set's: it changes only when an install
 * does, so it is cached until then (`q.plugins()` reaches it) and every
 * consumer of a dataset in a community shares one request.
 */

import { useMemo } from "react";

import { useReadFieldCatalog } from "@/api/generated/fields/fields";
import type {
  DefaultFilter,
  GroupingDescription,
  RelationDescription,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { type FilterFieldSpec, toFilterFieldSpec } from "@/lib/widgets/conditions";

const EMPTY: FilterFieldSpec[] = [];
const NO_RELATIONS: RelationDescription[] = [];
const NO_DEFAULTS: DefaultFilter[] = [];
const NO_GROUPINGS: GroupingDescription[] = [];

/**
 * The declarations, ready for the controls to read.
 *
 * The mapping lives here rather than at each call site: every consumer wants
 * the same shape, and two components doing it themselves is two places to keep
 * in step for no gain.
 */
export function useFieldCatalog(dataset: string) {
  const communityId = useActiveCommunityId();
  const query = useReadFieldCatalog(communityId, dataset, {
    query: {
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: Number.POSITIVE_INFINITY,
    },
  });

  const described = query.data?.fields;
  const fields = useMemo(() => (described ? described.map(toFilterFieldSpec) : EMPTY), [described]);

  return {
    /** Empty until it loads — a filter list with nothing in it renders as
     *  nothing, which is the right thing to show while it is on its way. */
    fields,
    /** What else this dataset can be read alongside. A related field is named
     *  `<relation>.<field>`, and what may be named is that dataset's own
     *  description — so a consumer reads this and then reads that. */
    relations: query.data?.relations ?? NO_RELATIONS,
    /** What a new statement about this dataset leaves out until its author
     *  says otherwise: archived rows, and templates. Ordinary conditions, so
     *  the builder seeds its filter list with them and they are shown and
     *  removed like any other. The trash is not among them — the query surface
     *  removes it in the database, and no filter can ask for it back. */
    defaultFilters: query.data?.default_filters ?? NO_DEFAULTS,
    /** The fields a list of the dataset can be grouped by, a date's by a
     *  bucket of the calendar. */
    groupings: query.data?.groupings ?? NO_GROUPINGS,
    isLoading: query.isLoading,
  };
}

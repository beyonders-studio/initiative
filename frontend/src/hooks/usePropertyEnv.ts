import { useMemo } from "react";

import { useFileFieldFiles } from "@/components/tools/files/useFileFieldFiles";
import {
  useAppendPropertyOption,
  useCreateProperty,
  useOwnedDefinitions,
} from "@/hooks/useProperties";
import { useSearchMembers } from "@/hooks/useUsers";
import type { PropertyEnv } from "@/ui/layouts/fieldEditors";
import type { MetadataOwner } from "@/ui/properties/propertyHelpers";

/**
 * What a page's property editors read and change through: the properties an
 * item in `initiativeId` may hold, with `owner`'s metadata, and the
 * community's ways to make a property or an option, find its members and find
 * and read the initiative's files.
 */
export const usePropertyEnv = ({
  initiativeId,
  owner,
  enabled,
}: {
  initiativeId: number | null;
  owner?: MetadataOwner;
  /** Whether the definitions are read: where the reader may change the item. */
  enabled: boolean;
}): PropertyEnv => {
  const definitions = useOwnedDefinitions({
    initiativeId: initiativeId ?? undefined,
    owner,
    enabled: enabled && initiativeId !== null,
  });
  const { mutateAsync: createProperty } = useCreateProperty();
  const appendOption = useAppendPropertyOption();
  const searchMembers = useSearchMembers();
  const files = useFileFieldFiles(initiativeId);
  return useMemo(
    () => ({ definitions, createProperty, appendOption, searchMembers, files }),
    [definitions, createProperty, appendOption, searchMembers, files]
  );
};

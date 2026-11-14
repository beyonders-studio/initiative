/**
 * Chooses one community on the deployment, searched on the server.
 *
 * Staff ask for access to a community by naming it, and an id typed from
 * memory names the wrong one as easily as the right one. Every community is
 * listed, deleted and suspended ones included — a moderator may need a grant
 * on exactly those — and each says when it is not active.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CommunityStatus,
  ListPlatformCommunityStorageSortBy,
} from "@/api/generated/initiativeAPI.schemas";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { Combobox } from "@/ui/combobox";

export interface PickedCommunity {
  id: number;
  /** Absent when only the id is known, as from a link that carried no name. */
  name?: string | null;
}

/** How a chosen community reads: its name and its id, so two of the same name
 *  are told apart. */
export const pickedCommunityLabel = (community: PickedCommunity): string =>
  community.name ? `${community.name} (#${community.id})` : `#${community.id}`;

export const CommunityPicker = ({
  value,
  onChange,
  disabled = false,
  "aria-label": ariaLabel,
  className,
}: {
  value: PickedCommunity | null;
  onChange: (community: PickedCommunity) => void;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}) => {
  const { t } = useTranslation("settings");
  const [search, setSearch] = useState("");
  // Only read while the list is open, a page at a time.
  const [open, setOpen] = useState(false);
  const communities = usePlatformCommunities(
    {
      search: search || undefined,
      sort_by: ListPlatformCommunityStorageSortBy.name,
      page_size: 20,
    },
    { enabled: open }
  );
  const rows = communities.data?.items ?? [];

  return (
    <Combobox
      className={className}
      aria-label={ariaLabel}
      value={value ? String(value.id) : null}
      selectedLabel={value ? pickedCommunityLabel(value) : null}
      items={rows.map((community) => ({
        value: String(community.id),
        label: community.name,
        hint:
          community.status === CommunityStatus.active
            ? `#${community.id}`
            : `${t(`communities.status.${community.status}`)} · #${community.id}`,
      }))}
      onSearchChange={setSearch}
      onOpenChange={setOpen}
      loading={communities.isFetching}
      placeholder={t("accessGrants.communityPlaceholder")}
      searchPlaceholder={t("accessGrants.communitySearch")}
      emptyMessage={t("accessGrants.communityEmpty")}
      disabled={disabled}
      onValueChange={(next) => {
        const picked = rows.find((community) => String(community.id) === next);
        if (picked) onChange({ id: picked.id, name: picked.name });
      }}
    />
  );
};

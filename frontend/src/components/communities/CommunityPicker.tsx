/**
 * Chooses one community on the deployment, or several with `multiple`,
 * searched on the server.
 *
 * Staff ask for access to a community by naming it, and an id typed from
 * memory names the wrong one as easily as the right one. Every community is
 * listed, deleted and suspended ones included — a moderator may need a grant
 * on exactly those — and each says when it is not active.
 */

import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CommunityStatus,
  ListPlatformCommunityStorageSortBy,
} from "@/api/generated/initiativeAPI.schemas";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
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

type CommunityPickerProps = {
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
} & (
  | {
      multiple?: false;
      value: PickedCommunity | null;
      onChange: (community: PickedCommunity) => void;
    }
  | {
      /** Picks as many as wanted, each shown below the field to take off again. */
      multiple: true;
      value: PickedCommunity[];
      onChange: (communities: PickedCommunity[]) => void;
    }
);

export const CommunityPicker = (props: CommunityPickerProps) => {
  const { disabled = false, "aria-label": ariaLabel, className } = props;
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

  const shared = {
    className,
    "aria-label": ariaLabel,
    items: rows.map((community) => ({
      value: String(community.id),
      label: community.name,
      hint:
        community.status === CommunityStatus.active
          ? `#${community.id}`
          : `${t(`communities.status.${community.status}`)} · #${community.id}`,
    })),
    onSearchChange: setSearch,
    onOpenChange: setOpen,
    loading: communities.isFetching,
    placeholder: t("accessGrants.communityPlaceholder"),
    searchPlaceholder: t("accessGrants.communitySearch"),
    emptyMessage: t("accessGrants.communityEmpty"),
    disabled,
  };

  if (!props.multiple) {
    const { value, onChange } = props;
    return (
      <Combobox
        {...shared}
        value={value ? String(value.id) : null}
        selectedLabel={value ? pickedCommunityLabel(value) : null}
        onValueChange={(next) => {
          const picked = rows.find((community) => String(community.id) === next);
          if (picked) onChange({ id: picked.id, name: picked.name });
        }}
      />
    );
  }

  const { value, onChange } = props;
  // The page of matches rarely holds every community already chosen, so each
  // is named from the value, and a new one from the page.
  const known = new Map<string, PickedCommunity>([
    ...rows.map((row) => [String(row.id), { id: row.id, name: row.name }] as const),
    ...value.map((community) => [String(community.id), community] as const),
  ]);

  return (
    <div className="space-y-2">
      <Combobox
        {...shared}
        multiple
        value={value.map((community) => String(community.id))}
        onValueChange={(next) => onChange(next.flatMap((id) => known.get(id) ?? []))}
      />
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {value.map((community) => {
            const label = pickedCommunityLabel(community);
            return (
              <li key={community.id}>
                <Badge variant="secondary">
                  {label}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4"
                    disabled={disabled}
                    aria-label={t("accessGrants.communityRemove", { name: label })}
                    onClick={() => onChange(value.filter((other) => other.id !== community.id))}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </Badge>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

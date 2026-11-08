import { ChevronsUpDown, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { cn } from "@/ui/lib/utils";

/** Someone a picker or a field may name, as they are drawn. */
export interface Member {
  id: number;
  name: string;
  /** Their picture; their initials are drawn where they have none. */
  picture?: string;
  initials: string;
}

/** Whose people are offered: the community's, those who can open one row, or
 *  one initiative's members. */
export type MemberScope =
  | { type: "community" }
  | { type: "canOpen"; tool: Tool; id: number | null | undefined }
  | { type: "initiative"; initiativeId: number | null | undefined };

/** The members of `scope` whose names match `search`, or those `ids` names. */
export type SearchMembers = (
  scope: MemberScope,
  query: { search: string } | { ids: number[] }
) => Promise<Member[]>;

export interface MemberPickerProps {
  /** Finds the people listed, and who a bare `value` names. */
  searchMembers: SearchMembers;
  scope: MemberScope;
  /** The person picked, by id; null for nobody. */
  value: number | null;
  /** Who `value` names, so the trigger shows them without a lookup. Without
   *  it, the value is looked up. */
  selected?: Member | null;
  /** The id picked and who it names; null for nobody. */
  onChange: (id: number | null, member: Member | null) => void;
  /** Shown in the trigger while nobody is picked, and in the search field. */
  placeholder: string;
  /** Shown when nobody matches. */
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}

const MemberAvatar = ({ member, className }: { member: Member; className?: string }) => (
  <Avatar className={cn("h-6 w-6 border text-3xs", className)}>
    {member.picture ? <AvatarImage src={member.picture} alt={member.name} /> : null}
    <AvatarFallback userId={member.id}>{member.initials}</AvatarFallback>
  </Avatar>
);

/** One of the people in `scope`, searched for by name while the list is open;
 *  or nobody. */
export const MemberPicker = ({
  searchMembers,
  scope,
  value,
  selected = null,
  onChange,
  placeholder,
  emptyMessage,
  disabled = false,
  className,
  "aria-label": ariaLabel,
}: MemberPickerProps) => {
  const { t } = useTranslation("ui");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  // Who the value names once it is picked or looked up.
  const [named, setNamed] = useState<Member | null>(null);

  // Kept by what it says, so a scope given afresh each render asks nothing new.
  const scopeKey = JSON.stringify(scope);
  const search = useCallback(
    (asked: Parameters<SearchMembers>[1]) => searchMembers(JSON.parse(scopeKey), asked),
    [searchMembers, scopeKey]
  );

  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoading(true);
    search({ search: query })
      .then((members) => {
        if (current) setFound(members);
      })
      .catch(() => undefined)
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [open, query, search]);

  const shown =
    value === null
      ? null
      : ([named, selected, ...found].find((each) => each?.id === value) ?? null);
  const unnamed = value !== null && shown === null ? value : null;
  useEffect(() => {
    if (unnamed === null) return;
    let current = true;
    search({ ids: [unnamed] })
      .then(([member]) => {
        if (current && member) setNamed(member);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [unnamed, search]);

  const drawn =
    shown ??
    (value === null
      ? null
      : { id: value, name: t("memberPicker.userWithId", { id: value }), initials: "?" });

  return (
    <Combobox
      items={[
        // Clearing is listed first while there is something to clear: "" is
        // no member's id.
        ...(value !== null ? [{ value: "", label: t("clear"), icon: X }] : []),
        ...found.map((member) => ({
          value: String(member.id),
          label: member.name,
          icon: <MemberAvatar member={member} />,
        })),
      ]}
      value={value !== null ? String(value) : null}
      onValueChange={(next) => {
        const member = found.find((each) => String(each.id) === next) ?? null;
        setNamed(member);
        onChange(member ? member.id : null, member);
      }}
      onSearchChange={setQuery}
      onOpenChange={setOpen}
      loading={loading && found.length === 0}
      searchPlaceholder={placeholder}
      emptyMessage={emptyMessage}
      disabled={disabled}
      trigger={
        <Button
          variant="outline"
          role="combobox"
          aria-label={ariaLabel}
          disabled={disabled}
          className={cn("w-full justify-between", !drawn && "text-muted-foreground", className)}
        >
          <span className="flex min-w-0 items-center gap-2">
            {drawn ? <MemberAvatar member={drawn} className="h-5 w-5 text-3xs" /> : null}
            <span className="truncate">{drawn ? drawn.name : placeholder}</span>
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      }
    />
  );
};

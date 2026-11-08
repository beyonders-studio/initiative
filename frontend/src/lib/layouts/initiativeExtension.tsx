/**
 * What Initiative adds to each of its kinds' details: the plug-ins installed
 * in an item's initiative, whose fields and parts are drawn on it, its links,
 * and the community it lives in.
 */

import { createContext, Fragment, useContext, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { DetailLayoutReadKind, EndpointRef } from "@/api/generated/initiativeAPI.schemas";
import { EntityLinkField } from "@/components/entities/EntityLinkField";
import type { RelationsLayout } from "@/components/entities/RelationsSection";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useProjectLayoutEnv } from "@/hooks/useLayoutEnv";
import { usePropertyEnv } from "@/hooks/usePropertyEnv";
import type { LinkedRef } from "@/lib/relationships";
import type { ToolRelationEntity } from "@/lib/tools";
import {
  type DetailExtension,
  type DetailItem,
  type DetailKind,
  type ItemHome,
  useItemHome,
} from "@/ui/layouts/DetailLayoutView";
import { ItemDraftContext } from "@/ui/layouts/editing";

import {
  FieldsInParts,
  fieldsInParts,
  PluginFieldOnDetail,
  pluginFields,
  pluginKindOf,
  pluginParts,
  shippedPluginParts,
  usePluginsOnItems,
} from "./plugins";

/** What an item's links are kept under: the tool entity, and the item itself
 *  where it is not that entity. */
export interface ItemLinks {
  entity: ToolRelationEntity;
  target?: EndpointRef;
  title?: string;
  layout?: RelationsLayout;
}

/** One of Initiative's kinds of item, whose home also says where an item's
 *  links are kept. */
export type InitiativeDetail<I extends DetailItem, C, P> = DetailKind<
  I,
  C,
  P,
  { links: ItemLinks }
>;

const useLinkedHome = useItemHome<{ links: ItemLinks }>;

/** The links an item being added is to be made with. */
export const AddingLinks = createContext<{
  value: LinkedRef[];
  onChange: (next: LinkedRef[]) => void;
} | null>(null);

const ItemRelations = () => {
  const home = useLinkedHome();
  return (
    <ToolRelationsPanel
      tool={home.canOpen.tool}
      entity={home.links.entity}
      target={home.links.target}
      canEdit={!home.readOnly}
      entityTitle={home.links.title}
      defaultLayout={home.links.layout}
    />
  );
};

/** What an item being added is to be linked to, written once it is made. */
const LinksToMake = () => {
  const { t } = useTranslation("relations");
  const home = useLinkedHome();
  const links = useContext(AddingLinks);
  if (!links || home.initiativeId === null) return null;
  return (
    <EntityLinkField
      label={t("groups.attached.title")}
      initiativeId={home.initiativeId}
      value={links.value}
      onChange={links.onChange}
    />
  );
};

const RELATIONS = { relations: () => <ItemRelations /> };
const LINKS_TO_MAKE = { relations: () => <LinksToMake /> };

// Nothing on a detail opens a task through its fields' links.
const NO_TASK = () => "";

/**
 * Initiative's extension of an item's detail, which each of its kinds draws
 * with. One being added draws what needs nothing saved: the links to make,
 * and nothing a plug-in draws.
 */
export const useInitiativeExtension = <I extends DetailItem>(
  home: Pick<ItemHome<unknown, unknown>, "initiativeId" | "owner" | "readOnly">,
  kind: DetailLayoutReadKind
): DetailExtension<I> => {
  const { i18n } = useTranslation();
  const communityId = useActiveCommunityId();
  const projectEnv = useProjectLayoutEnv(NO_TASK);
  // What the detail's property fields read and write, for a reader who may
  // change the item.
  const properties = usePropertyEnv({
    initiativeId: home.initiativeId,
    owner: home.owner,
    enabled: !home.readOnly,
  });
  const env = useMemo(() => ({ ...projectEnv, properties }), [projectEnv, properties]);
  const plugins = usePluginsOnItems(home.initiativeId, true, pluginKindOf(kind));
  const adding = useContext(ItemDraftContext) !== null;
  const fields = useMemo(() => pluginFields(plugins, i18n.language), [plugins, i18n.language]);
  const more = useMemo(() => shippedPluginParts(plugins), [plugins]);
  const parts = useMemo(
    () => (adding ? LINKS_TO_MAKE : { ...pluginParts(plugins), ...RELATIONS }),
    [adding, plugins]
  );
  return {
    env,
    fields,
    more,
    parts,
    // A plug-in's field, whose value is the plug-in's to change.
    field: (field, item) =>
      field.plugin ? <PluginFieldOnDetail plugins={plugins} field={field} item={item} /> : null,
    wrap: (tree, children) => (
      // An item of another community is another item, though its id is the
      // same: it starts afresh, with none of this one's drafts.
      <Fragment key={communityId}>
        <FieldsInParts.Provider value={fieldsInParts(tree, plugins)}>
          {children}
        </FieldsInParts.Provider>
      </Fragment>
    ),
  };
};

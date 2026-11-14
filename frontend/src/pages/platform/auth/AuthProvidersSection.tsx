import { useTranslation } from "react-i18next";

import {
  useAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useDiscoverAuthProvider,
  useTestAuthProvider,
  useUpdateAuthProvider,
} from "@/hooks/useSettings";

import { ProviderRegistrySection } from "./ProviderRegistrySection";

/** The operator-global login provider registry (platform Settings → Authentication). */
export const AuthProvidersSection = () => {
  const { t } = useTranslation("settings");
  const providersQuery = useAuthProviders();
  const createProvider = useCreateAuthProvider();
  const updateProvider = useUpdateAuthProvider();
  const deleteProvider = useDeleteAuthProvider();
  const testProvider = useTestAuthProvider();
  const discoverIssuer = useDiscoverAuthProvider();

  return (
    <ProviderRegistrySection
      title={t("authProviders.title")}
      description={t("authProviders.description")}
      dialogDescription={t("authProviders.dialogDescription")}
      providers={providersQuery.data}
      isLoading={providersQuery.isLoading}
      createProvider={createProvider}
      updateProvider={updateProvider}
      deleteProvider={deleteProvider}
      testProvider={testProvider}
      discoverIssuer={discoverIssuer}
    />
  );
};

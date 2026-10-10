import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  type AnyRouter,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { type RenderOptions, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories/community.factory";
import { buildUser } from "@/__tests__/factories/user.factory";
import { AuthContext } from "@/hooks/useAuth";
import { CommunityContext } from "@/hooks/useCommunities";
import { ServerContext } from "@/hooks/useServer";
import { ThemeContext } from "@/hooks/useTheme";
import type { RouterContext } from "@/router";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AuthOverrides = Partial<React.ComponentProps<typeof AuthContext.Provider>["value"]>;
type CommunityOverrides = Partial<React.ComponentProps<typeof CommunityContext.Provider>["value"]>;
type ServerOverrides = Partial<React.ComponentProps<typeof ServerContext.Provider>["value"]>;
type ThemeOverrides = Partial<React.ComponentProps<typeof ThemeContext.Provider>["value"]>;

interface ProviderOptions {
  auth?: AuthOverrides;
  communities?: CommunityOverrides;
  server?: ServerOverrides;
  theme?: ThemeOverrides;
  queryClient?: QueryClient;
}

interface RenderWithProvidersResult extends ReturnType<typeof render> {
  queryClient: QueryClient;
}

interface RenderPageResult extends RenderWithProvidersResult {
  /** The memory router the page is mounted in — read
   *  `router.state.location.pathname` to assert where a flow navigated. */
  router: AnyRouter;
}

interface RenderPageOptions extends ProviderOptions {
  routerSearch?: Record<string, unknown>;
  /** The route the page is mounted at. Use `$param` segments for a page that
   *  reads `useParams`, and supply their values via {@link routeParams}. */
  initialRoute?: string;
  /** Values for the `$param` segments in {@link initialRoute}. */
  routeParams?: Record<string, string>;
  /** Fragment the page starts at, without the leading "#". For a page that
   *  reads or rewrites the URL and has to carry the fragment along. */
  routerHash?: string;
}

// ---------------------------------------------------------------------------
// Query client factory
// ---------------------------------------------------------------------------

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Default context values
// ---------------------------------------------------------------------------

/** The context the shipped route tree is created with, for a test that builds
 *  a router from `routeTree.gen` to resolve its routes. The app's providers
 *  fill `auth`, `communities` and `server` in at runtime; a test that only matches
 *  routes needs none of them. */
export function buildRouterContext(): RouterContext {
  return {
    queryClient: createTestQueryClient(),
    auth: undefined,
    communities: undefined,
    server: undefined,
  };
}

function buildDefaultAuth(): React.ComponentProps<typeof AuthContext.Provider>["value"] {
  return {
    user: buildUser(),
    token: "test-token",
    loading: false,
    sessionUnverified: false,
    login: vi.fn(),
    completeSecondFactor: vi.fn(),
    applyPasskeySignIn: vi.fn(),
    register: vi.fn(),
    completeOidcLogin: vi.fn(),
    stepUpWithFactor: vi.fn(),
    stepUpWithPasskey: vi.fn(),
    stepUpWithEmailCode: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
    acceptUser: vi.fn(),
    applySignIn: vi.fn(),
  };
}

function buildDefaultCommunities(): React.ComponentProps<
  typeof CommunityContext.Provider
>["value"] {
  const community = buildCommunity();
  return {
    communities: [community],
    activeCommunityId: 1,
    activeCommunity: community,
    activeCommunityReadOnly: false,
    loading: false,
    error: null,
    refreshCommunities: vi.fn(),
    switchCommunity: vi.fn(),
    syncCommunityFromUrl: vi.fn(),
    createCommunity: vi.fn(),
    updateCommunityInState: vi.fn(),
    reorderCommunities: vi.fn(),
    canCreateCommunities: true,
  };
}

function buildDefaultServer(): React.ComponentProps<typeof ServerContext.Provider>["value"] {
  return {
    serverUrl: null,
    isNativePlatform: false,
    isServerConfigured: true,
    loading: false,
    setServerUrl: vi.fn(),
    clearServerUrl: vi.fn(),
    testServerConnection: vi.fn(),
    getServerHostname: vi.fn().mockReturnValue(null),
    getServerOrigin: vi.fn().mockReturnValue("http://localhost"),
  };
}

function buildDefaultTheme(): React.ComponentProps<typeof ThemeContext.Provider>["value"] {
  return {
    theme: "light",
    resolvedTheme: "light",
    setTheme: vi.fn(),
    toggleTheme: vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Provider wrapper
// ---------------------------------------------------------------------------

function buildWrapper(options: ProviderOptions = {}) {
  const queryClient = options.queryClient ?? createTestQueryClient();
  const auth = { ...buildDefaultAuth(), ...options.auth } as ReturnType<typeof buildDefaultAuth>;
  const communities = { ...buildDefaultCommunities(), ...options.communities } as ReturnType<
    typeof buildDefaultCommunities
  >;
  const server = { ...buildDefaultServer(), ...options.server } as ReturnType<
    typeof buildDefaultServer
  >;
  const theme = { ...buildDefaultTheme(), ...options.theme } as ReturnType<
    typeof buildDefaultTheme
  >;

  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ServerContext.Provider value={server}>
          <ThemeContext.Provider value={theme}>
            <AuthContext.Provider value={auth}>
              <CommunityContext.Provider value={communities}>{children}</CommunityContext.Provider>
            </AuthContext.Provider>
          </ThemeContext.Provider>
        </ServerContext.Provider>
      </QueryClientProvider>
    );
  }

  return { Wrapper, queryClient };
}

// ---------------------------------------------------------------------------
// renderWithProviders
// ---------------------------------------------------------------------------

export function renderWithProviders(
  ui: ReactElement,
  options: ProviderOptions & Omit<RenderOptions, "wrapper"> = {}
): RenderWithProvidersResult {
  const { auth, communities, server, theme, queryClient: qc, ...renderOptions } = options;
  const { Wrapper, queryClient } = buildWrapper({
    auth,
    communities,
    server,
    theme,
    queryClient: qc,
  });

  const result = render(ui, { wrapper: Wrapper, ...renderOptions });

  return { ...result, queryClient };
}

// ---------------------------------------------------------------------------
// renderPage - wraps a page component in a TanStack Router
// ---------------------------------------------------------------------------

export function renderPage(
  PageComponent: React.ComponentType,
  options: RenderPageOptions & Omit<RenderOptions, "wrapper"> = {}
): RenderPageResult {
  const {
    auth,
    communities,
    server,
    theme,
    queryClient: qc,
    routerSearch,
    initialRoute = "/",
    routeParams,
    routerHash,
    ...renderOptions
  } = options;

  const { Wrapper, queryClient } = buildWrapper({
    auth,
    communities,
    server,
    theme,
    queryClient: qc,
  });

  const rootRoute = createRootRoute();

  const childRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: initialRoute,
    component: PageComponent as () => ReactElement,
    // `routerSearch` seeds the first render only. Once the page navigates, its
    // own params win — otherwise a page that reads and rewrites the URL (say,
    // correcting an out-of-range `page`) could never be observed changing it.
    validateSearch: (search: Record<string, unknown>) =>
      Object.keys(search).length > 0 ? search : (routerSearch ?? {}),
  });

  const routeTree = rootRoute.addChildren([childRoute]);

  // The route pattern carries `$param` placeholders; the history entry needs
  // them filled in, or nothing matches.
  const withParams = routeParams
    ? Object.entries(routeParams).reduce(
        (path, [name, value]) => path.replaceAll(`$${name}`, value),
        initialRoute
      )
    : initialRoute;
  // The fragment rides on the history entry only — the route pattern above must
  // not carry it, or nothing matches.
  const initialEntry = routerHash ? `${withParams}#${routerHash}` : withParams;

  const history = createMemoryHistory({
    initialEntries: [initialEntry],
  });

  const router = createRouter({ routeTree, history });

  const result = render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
    renderOptions
  );

  return { ...result, queryClient, router };
}

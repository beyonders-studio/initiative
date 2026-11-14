/**
 * A listing's page, read again when the tab comes back.
 *
 * The seat buys a plug-in in the billing portal, in another tab, and the
 * statement that lets it install arrives seconds later. So a listing this
 * community cannot install yet is asked again on return however fresh it is;
 * one it can install keeps the catalog's long window. Both are read in the
 * reader's language, which billing words its offer in.
 */
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";

import { useMarketplaceListing, useMarketplaceListingByUid } from "./useMarketplace";

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 1 }));

const refocus = () => {
  focusManager.setFocused(false);
  focusManager.setFocused(true);
};

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

/** Every read of the listing, as the address it was asked at. */
let asked: URL[] = [];
let unavailable: unknown = null;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  asked = [];
  unavailable = null;
  const answer = ({ request }: { request: Request }) => {
    asked.push(new URL(request.url));
    return HttpResponse.json({ uid: "HOARD000000001", unavailable });
  };
  server.use(
    communityHttp.get("/marketplace/listings/by-uid/:uid", answer),
    communityHttp.get("/marketplace/listings/:publicId", answer)
  );
});

afterEach(() => {
  focusManager.setFocused(undefined);
  client.clear();
});

describe.each([
  ["by public id", () => useMarketplaceListing("tests.hoard")],
  ["by uid", () => useMarketplaceListingByUid("HOARD000000001")],
])("a listing read %s", (_how, useListing) => {
  it("is asked in the reader's language", async () => {
    const { result } = renderHook(useListing, { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(asked[0]?.searchParams.get("locale")).toBe("en");
  });

  it("is asked again on return while this community cannot install it", async () => {
    unavailable = { reason: "entitlement_required", action_url: null, offer: null };
    const { result } = renderHook(useListing, { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // The statement arrived meanwhile.
    unavailable = null;
    refocus();

    await waitFor(() => expect(result.current.data?.unavailable).toBeNull());
    expect(asked).toHaveLength(2);
  });

  it("keeps the catalog's window once it can", async () => {
    const { result } = renderHook(useListing, { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    refocus();

    // Nothing asked: give a refetch the chance it would have taken.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(asked).toHaveLength(1);
  });
});

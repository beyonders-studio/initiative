/**
 * What a plug-in asked to do as the viewer, one line per purpose, and the
 * viewer's answer.
 *
 * Each request is answered on its own, never beyond what the plug-in asked for:
 * a request to read offers reading only, and one to read and change offers
 * both. Declining a waiting request and withdrawing an allowed one are the
 * same act on the server, told apart here by what the line said before.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import {
  type CommunityPluginConsentRead,
  ConsentAccess,
  ConsentStatus,
} from "@/api/generated/initiativeAPI.schemas";
import { TooltipProvider } from "@/ui/tooltip";

import { PluginConsentRequests } from "./PluginConsentRequests";

const grantConsent = vi.fn();
const revokeConsent = vi.fn();

vi.mock("@/hooks/useCommunityPluginDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPluginDetail")>()),
  useGrantPluginConsent: () => ({ mutateAsync: grantConsent, isPending: false }),
  useRevokePluginConsent: () => ({ mutateAsync: revokeConsent, isPending: false }),
}));

vi.mock("@/hooks/useInitiatives", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useInitiatives")>()),
  useInitiatives: () => ({ data: [{ id: 9, name: "Launch" }] }),
}));

const consent = (
  overrides: Partial<CommunityPluginConsentRead> = {}
): CommunityPluginConsentRead => ({
  id: 41,
  purpose: "node-1",
  label: "Comment on the linked issue",
  initiative_id: null,
  requested_access: ConsentAccess.read_write,
  granted_access: null,
  status: ConsentStatus.pending,
  requested_at: "2026-09-24T00:00:00Z",
  granted_at: null,
  revoked_at: null,
  ...overrides,
});

const render = (consents: CommunityPluginConsentRead[]) =>
  renderPage(() => (
    <TooltipProvider>
      <PluginConsentRequests pluginId={3} pluginName="Auto" consents={consents} />
    </TooltipProvider>
  ));

beforeEach(() => {
  grantConsent.mockReset().mockResolvedValue(undefined);
  revokeConsent.mockReset().mockResolvedValue(undefined);
});

describe("PluginConsentRequests", () => {
  it("shows the plug-in's own words and waits for an answer", async () => {
    render([consent()]);
    expect(await screen.findByText("Auto: “Comment on the linked issue”")).toBeInTheDocument();
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });

  it("offers both levels when the plug-in asked for changes, and answers that one line", async () => {
    render([consent()]);
    fireEvent.click(await screen.findByText("Let it read and change things as me"));
    await waitFor(() =>
      expect(grantConsent).toHaveBeenCalledWith({
        consentId: 41,
        access: ConsentAccess.read_write,
      })
    );

    grantConsent.mockClear();
    fireEvent.click(screen.getByText("Let it read as me"));
    await waitFor(() =>
      expect(grantConsent).toHaveBeenCalledWith({ consentId: 41, access: ConsentAccess.read })
    );
  });

  it("never offers more than the plug-in asked for", async () => {
    render([consent({ requested_access: ConsentAccess.read })]);
    expect(await screen.findByText("Let it read as me")).toBeInTheDocument();
    expect(screen.queryByText("Let it read and change things as me")).toBeNull();
  });

  it("declines a waiting request", async () => {
    render([consent()]);
    fireEvent.click(await screen.findByText("Decline"));
    await waitFor(() => expect(revokeConsent).toHaveBeenCalledWith(41));
  });

  it("withdraws, or narrows to reading, what was allowed", async () => {
    render([
      consent({
        status: ConsentStatus.granted,
        granted_access: ConsentAccess.read_write,
        granted_at: "2026-09-24T01:00:00Z",
      }),
    ]);
    expect(await screen.findByText("Can read and change as you")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Only let it read"));
    await waitFor(() =>
      expect(grantConsent).toHaveBeenCalledWith({ consentId: 41, access: ConsentAccess.read })
    );
    fireEvent.click(screen.getByText("Stop this"));
    await waitFor(() => expect(revokeConsent).toHaveBeenCalledWith(41));
  });

  it("says where a purpose is bound, and which request is plug-in-wide", async () => {
    render([
      consent({ id: 1, purpose: null, label: "Act as you in its own screens" }),
      consent({ id: 2, initiative_id: 9 }),
    ]);
    expect(await screen.findByText(/Anything it does/)).toBeInTheDocument();
    expect(screen.getByText(/Only in Launch/)).toBeInTheDocument();
  });

  it("offers a declined request again", async () => {
    render([consent({ status: ConsentStatus.declined, revoked_at: "2026-09-24T02:00:00Z" })]);
    expect(await screen.findByText("Declined")).toBeInTheDocument();
    expect(screen.getByText("Let it read as me")).toBeInTheDocument();
    expect(screen.queryByText("Decline")).toBeNull();
  });
});

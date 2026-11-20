/**
 * The notice above the Create account button.
 *
 * Two things carry the weight. It must not appear on a deployment that has no
 * terms — a self-hoster being told they agree to somebody else's would be
 * plainly wrong — and where it does appear it has to name every required
 * document and
 * let them be read, because pressing the button is the agreement and an
 * agreement you cannot read first is not one.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const useLegalIndex = vi.fn();

vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => useLegalIndex(),
}));

import { LegalNotice } from "@/components/auth/LegalNotice";

type Doc = { slug: string; title: string; url?: string | null };

const TERMS: Doc = { slug: "terms", title: "Terms of Service" };
const PRIVACY: Doc = { slug: "privacy", title: "Privacy Policy" };

const hosted = (requiredDocuments: Doc[], documents: Doc[] = requiredDocuments) => {
  useLegalIndex.mockReturnValue({ enabled: true, documents, requiredDocuments, isLoading: false });
};

describe("LegalNotice", () => {
  // A deployment with no terms of its own, or one whose terms sit in its own
  // contract (an enterprise, or an employment one): signup asks for nothing.
  it.each([
    [{ enabled: false, documents: [], requiredDocuments: [] }],
    [{ enabled: true, documents: [PRIVACY], requiredDocuments: [] }],
  ])("says nothing where the deployment requires nothing", (index) => {
    useLegalIndex.mockReturnValue({ ...index, isLoading: false });

    const { container } = renderWithProviders(<LegalNotice />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names each required document and links each one", () => {
    hosted([TERMS, PRIVACY]);

    renderWithProviders(<LegalNotice />);

    const terms = screen.getByRole("link", { name: "Terms of Service" });
    const privacy = screen.getByRole("link", { name: "Privacy Policy" });
    expect(terms).toHaveAttribute("href", "/legal/terms");
    expect(privacy).toHaveAttribute("href", "/legal/privacy");
    // Beside the form rather than instead of it: reading one must not lose
    // what somebody has already typed.
    expect(terms).toHaveAttribute("target", "_blank");
    expect(privacy).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/by creating an account you agree/i)).toBeInTheDocument();
  });

  it("names only what the portal marks required", () => {
    hosted([TERMS], [TERMS, PRIVACY, { slug: "sla", title: "Service Levels" }]);

    renderWithProviders(<LegalNotice />);

    expect(screen.getByRole("link", { name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Privacy Policy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Service Levels" })).not.toBeInTheDocument();
  });

  it("links a document kept elsewhere where it is kept", () => {
    hosted([{ slug: "contract", title: "Master Agreement", url: "https://legal.example/msa" }]);

    renderWithProviders(<LegalNotice />);

    expect(screen.getByRole("link", { name: "Master Agreement" })).toHaveAttribute(
      "href",
      "https://legal.example/msa"
    );
  });
});

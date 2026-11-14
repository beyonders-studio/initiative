import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AnnouncementOperatorRead } from "@/api/generated/initiativeAPI.schemas";

import { AnnouncementsPage } from "./AnnouncementsPage";

const live: AnnouncementOperatorRead = {
  key: "db:1",
  id: 1,
  title: "Board view is new",
  category: "feature",
  sections: [{ heading: "Look", body: "At this" }],
  published_at: "2026-09-01T00:00:00Z",
  is_builtin: false,
  min_platform_role: "member",
  community_admins_only: false,
};

const draft: AnnouncementOperatorRead = {
  ...live,
  key: "db:2",
  id: 2,
  title: "Not ready yet",
  published_at: null,
};

const builtin: AnnouncementOperatorRead = {
  ...live,
  key: "builtin:breaking",
  id: null,
  title: "Something moved",
  category: "breaking",
  is_builtin: true,
};

const listResponds = (items: AnnouncementOperatorRead[]) => {
  server.use(http.get("*/api/v1/announcements/operator", () => HttpResponse.json({ items })));
};

describe("AnnouncementsPage", () => {
  it("lists announcements with their state", async () => {
    listResponds([live, draft]);

    renderWithProviders(<AnnouncementsPage />);

    expect(await screen.findByText("Board view is new")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Not ready yet")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("cannot edit or delete a notice compiled into the app", async () => {
    listResponds([builtin]);

    renderWithProviders(<AnnouncementsPage />);

    await screen.findByText("Something moved");
    expect(screen.getByText("Built in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("writes a new announcement with its sections", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    listResponds([]);
    server.use(
      http.post("*/api/v1/announcements/operator", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...live, ...posted }, { status: 201 });
      })
    );

    renderWithProviders(<AnnouncementsPage />);

    await user.click(await screen.findByRole("button", { name: /new announcement/i }));
    await user.type(screen.getByLabelText("Title"), "Filters moved");
    await user.type(screen.getByPlaceholderText(/section heading/i), "Where they went");
    await user.type(screen.getByPlaceholderText(/markdown is supported/i), "Up top now.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      title: "Filters moved",
      sections: [{ heading: "Where they went", body: "Up top now." }],
    });
  });

  it("saves the page break a section was given", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    listResponds([]);
    server.use(
      http.post("*/api/v1/announcements/operator", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...live, ...posted }, { status: 201 });
      })
    );

    renderWithProviders(<AnnouncementsPage />);

    await user.click(await screen.findByRole("button", { name: /new announcement/i }));
    await user.type(screen.getByLabelText("Title"), "Two parter");
    await user.type(screen.getByPlaceholderText(/section heading/i), "Page one");
    await user.click(screen.getByRole("button", { name: /add section/i }));

    const headings = screen.getAllByPlaceholderText(/section heading/i);
    await user.type(headings[1], "Page two");
    await user.click(screen.getByRole("switch", { name: /start a new page/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      sections: [
        { heading: "Page one", starts_page: false },
        { heading: "Page two", starts_page: true },
      ],
    });
  });

  it("names a bad trigger pattern in the form instead of posting it", async () => {
    const user = userEvent.setup();
    let posted = false;
    listResponds([]);
    server.use(
      http.post("*/api/v1/announcements/operator", () => {
        posted = true;
        return HttpResponse.json(live, { status: 201 });
      })
    );

    renderWithProviders(<AnnouncementsPage />);

    await user.click(await screen.findByRole("button", { name: /new announcement/i }));
    await user.type(screen.getByLabelText("Title"), "Help on the projects page");
    await user.type(screen.getByPlaceholderText(/section heading/i), "Over here");
    await user.type(screen.getByLabelText(/show on page/i), "c/*/settings");

    expect(await screen.findByText(/start the pattern with a \//i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(posted).toBe(false);

    // Correcting it clears the message and lets the save through.
    await user.clear(screen.getByLabelText(/show on page/i));
    await user.type(screen.getByLabelText(/show on page/i), "/c/*/settings");
    expect(screen.queryByText(/start the pattern with a \//i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted).toBe(true));
  });

  it("saves which accounts a notice is for", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    listResponds([]);
    server.use(
      http.post("*/api/v1/announcements/operator", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...live, ...posted }, { status: 201 });
      })
    );

    renderWithProviders(<AnnouncementsPage />);

    await user.click(await screen.findByRole("button", { name: /new announcement/i }));
    await user.type(screen.getByLabelText("Title"), "Your sidebar changed");
    await user.type(screen.getByPlaceholderText(/section heading/i), "What moved");

    await user.click(screen.getByRole("combobox", { name: /accounts this is for/i }));
    await user.click(await screen.findByRole("option", { name: /existed when it was published/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({ audience_accounts: "existing" });
  });

  it("refuses to save an announcement with no sections", async () => {
    const user = userEvent.setup();
    let posted = false;
    listResponds([]);
    server.use(
      http.post("*/api/v1/announcements/operator", () => {
        posted = true;
        return HttpResponse.json(live, { status: 201 });
      })
    );

    renderWithProviders(<AnnouncementsPage />);

    await user.click(await screen.findByRole("button", { name: /new announcement/i }));
    await user.type(screen.getByLabelText("Title"), "Empty");
    await user.click(screen.getByRole("button", { name: "Save" }));

    // The editor stays open and nothing is sent — the guard is client-side.
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Empty"));
    expect(posted).toBe(false);
  });
});

import { expect, type Page } from "@playwright/test";

/**
 * Barovia Arc, the seed's horror campaign (scripts/seed/projects.py): dated
 * tasks a few weeks either side of today, a Milestone and an Idea among them,
 * tasks that wait on others, and three that are part of the Death House.
 * Reached from its bookmark, as admin1 has it.
 */
export async function openBarovia(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await page.getByRole("link", { name: /Barovia Arc/ }).click();
  await expect(page.getByRole("heading", { name: "Barovia Arc", level: 1 })).toBeVisible();
}

/** Switch the project's tasks to `layout`, grouped by `groupBy`. */
export async function showTasks(page: Page, layout: "Table" | "Board" | "Gantt", groupBy = "None") {
  const menu = page.getByRole("combobox", { name: "Layout" });
  await menu.click();
  await page.getByRole("option", { name: layout }).click();
  await page.getByRole("combobox", { name: "Group by" }).click();
  await page.getByRole("option", { name: groupBy, exact: true }).click();
}

/** The project's task list: its heading, toolbar and the list itself, scrolled
 *  to the top of the window, clear of the buttons floating over its corner. */
export async function taskSection(page: Page) {
  const heading = page.getByRole("heading", { name: "Project tasks" });
  await heading.evaluate((element) => element.scrollIntoView({ block: "start" }));
  return heading.locator(
    "xpath=ancestor::*[.//*[@role='treegrid'] or .//table or .//button[starts-with(@aria-label, 'Collapse ')]][1]"
  );
}

import { describe, expect, it } from "vitest";

import { buildInitiative } from "@/__tests__/factories";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { linkableToolTypes } from "@/lib/references";
import { TOOLS } from "@/lib/tools";

// Every master switch on, derived from the registry rather than listed: a new
// toggleable tool is switched on here the day it exists, so the "is the tools"
// case below keeps meaning what it says.
const allSwitchesOn = Object.fromEntries(TOOLS.map((tool) => [tool, true]));

const enabled = (overrides = {}) => buildInitiative({ tools: { ...allSwitchesOn, ...overrides } });

describe("what [[ ]] can reach", () => {
  // Never what lives inside a tool: a task needs a project, an event needs a
  // calendar and a time, so `#` is how you reach them.
  it("is the tools, derived from the enum", () => {
    expect(linkableToolTypes(enabled()).sort()).toEqual(Object.values(Tool).map(String).sort());
  });

  it("leaves out a tool this initiative switched off", () => {
    const types = linkableToolTypes(enabled({ wiki: false }));
    expect(types).not.toContain(SearchEntityType.wiki);
    // The rest are untouched.
    expect(types).toContain(SearchEntityType.calendar);
    // The core tools have no switch to turn off.
    expect(types).toContain(SearchEntityType.project);
    expect(types).toContain(SearchEntityType.file);
  });
});

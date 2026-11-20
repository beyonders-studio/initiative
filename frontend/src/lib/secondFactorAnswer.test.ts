import { describe, expect, it } from "vitest";

import { classifySecondFactorAnswer } from "./secondFactorAnswer";

describe("classifySecondFactorAnswer", () => {
  it.each([
    ["123456", { code: "123456" }],
    // What an authenticator displays, and what gets pasted.
    ["123 456", { code: "123456" }],
    ["  123456 ", { code: "123456" }],
    // A recovery code is five-character groups, so six digits split by dashes
    // is somebody typing a live code with separators.
    ["12-34-56", { code: "123456" }],
    ["abcde-fghij-klmno-p", { recovery_code: "abcde-fghij-klmno-p" }],
    [" 4phx6-mpc7t-7sptb-3 ", { recovery_code: "4phx6-mpc7t-7sptb-3" }],
  ])("reads %j as %j", (answer, expected) => {
    expect(classifySecondFactorAnswer(answer)).toEqual(expected);
  });
});

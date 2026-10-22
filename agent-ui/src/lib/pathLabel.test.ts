// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { PATH_BUDGET, splitPathTail } from "@/lib/pathLabel";

describe("splitPathTail", () => {
  it("leaves a path that fits alone", () => {
    expect(splitPathTail("src/lib/card.test.ts")).toEqual({
      head: "",
      tail: "src/lib/card.test.ts",
    });
  });

  it("keeps the file name and elides whole leading segments", () => {
    const { head, tail } = splitPathTail(
      "packages/business-web/src/screens/SignupWizard/steps/__tests__/DateOfBirthStep.test.tsx"
    );

    expect(tail).toBe("DateOfBirthStep.test.tsx");
    expect(head).toBe("…/steps/__tests__/");
    expect(head).not.toContain("DateOfBirth");
    expect(head.length + tail.length).toBeLessThanOrEqual(PATH_BUDGET);
  });

  it("never exceeds the budget", () => {
    for (const path of [
      "a/very/deep/nested/directory/chain/that/keeps/going/DateOfBirthStep.test.tsx",
      "src/screens/SignupWizard/steps/__tests__/AnExtremelyLongFileNameThatCannotFitAnywhere.test.tsx",
      "x".repeat(120),
    ]) {
      const { head, tail } = splitPathTail(path);
      expect(head.length + tail.length).toBeLessThanOrEqual(PATH_BUDGET);
    }
  });

  it("cuts inside an oversized file name rather than hiding it", () => {
    const name =
      "AnExtremelyLongFileNameThatCannotFitInTheRowAtAllNoMatterWhat.test.tsx";
    const { head, tail } = splitPathTail(`src/${name}`);

    expect(head).toBe("");
    expect(tail.startsWith("…")).toBe(true);
    expect(tail.endsWith(".test.tsx")).toBe(true);
  });

  it("handles Windows separators", () => {
    const { head, tail } = splitPathTail(
      "packages\\business-web\\src\\screens\\SignupWizard\\steps\\__tests__\\DateOfBirthStep.test.tsx"
    );

    expect(tail).toBe("DateOfBirthStep.test.tsx");
    expect(head).toBe("…\\steps\\__tests__\\");
  });
});

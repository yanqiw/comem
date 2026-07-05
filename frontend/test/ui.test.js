import { describe, expect, test } from "vitest";

import {
  boardStatusSortValue,
  eventDetail,
  queueEntries,
  restoreHorizontalScroll,
  statusLabel,
} from "../src/ui.js";

describe("coordination console ui helpers", () => {
  test("orders board lanes by the documented workflow", () => {
    const lanes = {
      blocked: [],
      accepted: [],
      running: [],
      needs_fix: [],
      ready: [],
      awaiting_review: [],
      rejected: [],
      awaiting_human: [],
    };

    expect(queueEntries(lanes).map(([lane]) => lane)).toEqual([
      "ready",
      "running",
      "awaiting_human",
      "awaiting_review",
      "needs_fix",
      "accepted",
      "rejected",
      "blocked",
    ]);
    expect(boardStatusSortValue("unknown")).toBe(999);
  });

  test("formats machine statuses and events for people", () => {
    expect(statusLabel("awaiting_review")).toBe("awaiting review");
    expect(
      eventDetail({
        event_type: "verification_reported",
        payload: { invariant_key: "build", outcome: "passed" },
      }),
    ).toBe("build = passed");
  });

  test("restores horizontal board scroll without exceeding available range", () => {
    const node = { scrollLeft: 0, scrollWidth: 1200, clientWidth: 500 };

    restoreHorizontalScroll(node, 640);
    expect(node.scrollLeft).toBe(640);

    restoreHorizontalScroll(node, 900);
    expect(node.scrollLeft).toBe(700);
  });
});

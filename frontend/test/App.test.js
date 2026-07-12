// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "../src/App.svelte";

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: vi.fn().mockResolvedValue(data),
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function humanBrief(runId, goal) {
  return {
    run_id: runId,
    assignment_id: `assignment-${runId}`,
    brief: {
      schema_version: 1,
      current_goal: goal,
      current_stage: "implementing",
      recent_progress: [],
      decisions_and_risks: [],
      human_intervention: { needed: false, blocking: false },
      next_steps: [],
      context_refs: [],
    },
    source_event_sequence: 1,
    latest_event_sequence: 1,
    updated_at: "2026-07-12T08:00:00Z",
    freshness: "fresh",
  };
}

function replaceRoute(hash) {
  window.history.replaceState(null, "", hash);
}

function routeFetch(handler) {
  const fetchMock = vi.fn((path) => {
    if (path === "/api/version") return Promise.resolve(jsonResponse({ version: "test" }));
    if (path === "/api/teams") return Promise.resolve(jsonResponse([]));
    return handler(path);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function dashboardFetch(attention) {
  return routeFetch((path) => {
    if (path === "/api/board?team_id=default") {
      return Promise.resolve(
        jsonResponse({ team: { team_id: "default", name: "Default" }, lanes: { running: [] } }),
      );
    }
    if (path === "/api/attention?team_id=default") {
      return Promise.resolve(jsonResponse(attention));
    }
    if (path === "/api/governance?team_id=default") {
      return Promise.resolve(jsonResponse({ counts: { contracts: 0 } }));
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
}

function runDetail(runId) {
  return {
    run_id: runId,
    assignment_id: `assignment-${runId}`,
    status: "running",
    events: [],
  };
}

function assignmentDetail(assignmentId, activeRunId) {
  return {
    assignment: {
      assignment_id: assignmentId,
      title: assignmentId,
      status: "running",
      active_run_id: activeRunId,
    },
    runs: [],
    events: [],
  };
}

async function flushAsync() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await tick();
}

beforeEach(() => {
  const values = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  replaceRoute("#/");
});

test("an old assignment Brief cannot overwrite a newer run route", async () => {
  const assignmentBrief = deferred();
  const fetchMock = routeFetch((path) => {
    if (path === "/api/assignments/assignment-a") {
      return Promise.resolve(
        jsonResponse({
          assignment: {
            assignment_id: "assignment-a",
            title: "Assignment A",
            status: "running",
            active_run_id: "run-a",
          },
          runs: [],
          events: [],
        }),
      );
    }
    if (path === "/api/runs/run-a/brief") return assignmentBrief.promise;
    if (path === "/api/runs/run-b") {
      return Promise.resolve(
        jsonResponse({
          run_id: "run-b",
          assignment_id: "assignment-b",
          status: "running",
          events: [],
        }),
      );
    }
    if (path === "/api/runs/run-b/brief") {
      return Promise.resolve(jsonResponse(humanBrief("run-b", "Goal B")));
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
  replaceRoute("#/assignments/assignment-a");

  render(App);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/runs/run-a/brief"));

  replaceRoute("#/runs/run-b");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(await screen.findByText("Goal B")).toBeTruthy();

  assignmentBrief.resolve(jsonResponse(humanBrief("run-a", "Goal A")));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await tick();

  expect(screen.queryByText("Goal A")).toBeNull();
  expect(screen.getByText("Goal B")).toBeTruthy();
});

test("renders red before yellow regardless of API item order", async () => {
  dashboardFetch({
    counts: { red: 1, yellow: 1, green: 1 },
    items: [
      {
        event_id: "yellow-event",
        level: "yellow",
        reason_code: "review_soon",
        why_now: "Review soon",
        recommended_action: "Review next",
        run_id: "run-yellow",
        assignment_id: "assignment-yellow",
      },
      {
        event_id: "green-event",
        level: "green",
        reason_code: "resolved",
        why_now: "Resolved item",
        recommended_action: "None",
        run_id: "run-green",
        assignment_id: "assignment-green",
      },
      {
        event_id: "red-event",
        level: "red",
        reason_code: "decision",
        why_now: "Decide now",
        recommended_action: "Choose an option",
        decision_packet: { summary: "Choose safely" },
        run_id: "run-red",
        assignment_id: "assignment-red",
      },
    ],
  });
  replaceRoute("#/");

  const { container } = render(App);
  await screen.findByText("Decide now");

  const labels = [...container.querySelectorAll(".attention-item-head strong")].map(
    (element) => element.textContent,
  );
  expect(labels).toEqual(["必须现在介入", "建议关注"]);
});

test("hides green cards while retaining the green count", async () => {
  dashboardFetch({
    counts: { red: 0, yellow: 0, green: 1 },
    items: [
      {
        event_id: "green-event",
        level: "green",
        why_now: "Resolved item",
        recommended_action: "None",
        run_id: "run-green",
        assignment_id: "assignment-green",
      },
    ],
  });
  replaceRoute("#/");

  const { container } = render(App);
  expect(await screen.findByText("绿 1")).toBeTruthy();
  expect(container.querySelectorAll(".attention-item")).toHaveLength(0);
  expect(screen.queryByText("Resolved item")).toBeNull();
});

test("places Human Attention before the lifecycle board", async () => {
  dashboardFetch({ counts: { red: 0, yellow: 0, green: 0 }, items: [] });
  replaceRoute("#/");

  const { container } = render(App);
  await screen.findByText("当前没有需要你介入的事项");

  const attention = container.querySelector(".attention-console");
  const lifecycle = container.querySelector(".product-board");
  expect(attention.compareDocumentPosition(lifecycle) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});

test("shows the exact Human Attention empty state", async () => {
  dashboardFetch({ counts: { red: 0, yellow: 0, green: 3 }, items: [] });
  replaceRoute("#/");

  render(App);

  expect(await screen.findByText("当前没有需要你介入的事项", { exact: true })).toBeTruthy();
  expect(screen.getByText("绿 3")).toBeTruthy();
});

test.each([
  {
    name: "run 400",
    hash: "#/runs/run-missing",
    detailPath: "/api/runs/run-missing",
    detail: runDetail("run-missing"),
    briefPath: "/api/runs/run-missing/brief",
    status: 400,
  },
  {
    name: "assignment active run 404",
    hash: "#/assignments/assignment-missing",
    detailPath: "/api/assignments/assignment-missing",
    detail: assignmentDetail("assignment-missing", "run-active"),
    briefPath: "/api/runs/run-active/brief",
    status: 404,
  },
])("shows the missing Brief state for $name", async ({ hash, detailPath, detail, briefPath, status }) => {
  const fetchMock = routeFetch((path) => {
    if (path === detailPath) return Promise.resolve(jsonResponse(detail));
    if (path === briefPath) {
      return Promise.resolve(jsonResponse({ error: "human brief not found" }, status));
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
  replaceRoute(hash);

  render(App);

  expect(await screen.findByText("尚无 Human Resume Brief", { exact: true })).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith(briefPath);
});

test("surfaces a current Brief 500 through the existing error state", async () => {
  routeFetch((path) => {
    if (path === "/api/runs/run-error") return Promise.resolve(jsonResponse(runDetail("run-error")));
    if (path === "/api/runs/run-error/brief") {
      return Promise.resolve(jsonResponse({ error: "brief exploded" }, 500));
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
  replaceRoute("#/runs/run-error");

  render(App);

  expect(await screen.findByText("Couldn't load: brief exploded", { exact: true })).toBeTruthy();
});

test("a stale Brief failure cannot replace the current route with an error", async () => {
  const staleBrief = deferred();
  routeFetch((path) => {
    if (path === "/api/assignments/assignment-a") {
      return Promise.resolve(jsonResponse(assignmentDetail("assignment-a", "run-a")));
    }
    if (path === "/api/runs/run-a/brief") return staleBrief.promise;
    if (path === "/api/runs/run-b") return Promise.resolve(jsonResponse(runDetail("run-b")));
    if (path === "/api/runs/run-b/brief") {
      return Promise.resolve(jsonResponse(humanBrief("run-b", "Goal B")));
    }
    throw new Error(`unexpected fetch: ${path}`);
  });
  replaceRoute("#/assignments/assignment-a");

  render(App);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/runs/run-a/brief"));
  replaceRoute("#/runs/run-b");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(await screen.findByText("Goal B")).toBeTruthy();

  staleBrief.resolve(jsonResponse({ error: "stale failure" }, 500));
  await flushAsync();

  expect(screen.queryByText("Couldn't load: stale failure")).toBeNull();
  expect(screen.getByText("Goal B")).toBeTruthy();
});

test("a stale route cannot clear loading for the current route", async () => {
  const staleBrief = deferred();
  const currentBrief = deferred();
  const fetchMock = routeFetch((path) => {
    if (path === "/api/assignments/assignment-a") {
      return Promise.resolve(jsonResponse(assignmentDetail("assignment-a", "run-a")));
    }
    if (path === "/api/runs/run-a/brief") return staleBrief.promise;
    if (path === "/api/runs/run-b") return Promise.resolve(jsonResponse(runDetail("run-b")));
    if (path === "/api/runs/run-b/brief") return currentBrief.promise;
    throw new Error(`unexpected fetch: ${path}`);
  });
  replaceRoute("#/assignments/assignment-a");

  render(App);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/runs/run-a/brief"));
  replaceRoute("#/runs/run-b");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/runs/run-b/brief"));

  staleBrief.resolve(jsonResponse(humanBrief("run-a", "Goal A")));
  await flushAsync();
  expect(screen.getByText("Loading...")).toBeTruthy();

  currentBrief.resolve(jsonResponse(humanBrief("run-b", "Goal B")));
  expect(await screen.findByText("Goal B")).toBeTruthy();
});

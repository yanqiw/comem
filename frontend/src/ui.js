export const empty = "-";

export const boardStatusOrder = {
  proposed: 10,
  ready: 10,
  claimed: 20,
  running: 20,
  awaiting_human: 30,
  awaiting_approval: 40,
  awaiting_review: 40,
  needs_fix: 50,
  accepted: 60,
  rejected: 70,
  stalled: 80,
  blocked: 80,
  cancelled: 90,
  superseded: 100,
};

export const attentionStatuses = new Set([
  "awaiting_human",
  "needs_fix",
  "blocked",
  "stalled",
  "rejected",
]);

export function boardStatusSortValue(status) {
  return boardStatusOrder[status] || 999;
}

export function queueEntries(lanes) {
  return Object.entries(lanes || {}).sort(
    (a, b) => boardStatusSortValue(a[0]) - boardStatusSortValue(b[0]) || a[0].localeCompare(b[0]),
  );
}

export function queueTotal(lanes) {
  return Object.values(lanes || {}).reduce((sum, items) => sum + items.length, 0);
}

export function queueAttentionTotal(lanes) {
  return Object.entries(lanes || {}).reduce(
    (sum, [status, items]) => sum + (attentionStatuses.has(status) ? items.length : 0),
    0,
  );
}

export function queueActiveTotal(lanes) {
  const active = new Set(["running", "claimed", "ready", "awaiting_review", "awaiting_approval"]);
  return Object.entries(lanes || {}).reduce(
    (sum, [status, items]) => sum + (active.has(status) ? items.length : 0),
    0,
  );
}

export function statusTone(status) {
  if (["blocked", "stalled", "rejected", "awaiting_human"].includes(status)) return "critical";
  if (["needs_fix", "repair_ready"].includes(status)) return "warn";
  if (["running", "claimed", "awaiting_review", "awaiting_approval", "verifying"].includes(status))
    return "active";
  if (status === "accepted") return "success";
  return "neutral";
}

export function badgeColor(status) {
  return {
    awaiting_human: "red",
    repair_ready: "blue",
    awaiting_acceptor: "green",
    verifying: "",
    accepted: "green",
    criteria_sealed: "blue",
    drafting: "",
    rejected: "red",
    cancelled: "",
    running: "blue",
    claimed: "blue",
    ready: "",
    proposed: "",
    archived: "amber",
    awaiting_review: "blue",
    awaiting_approval: "blue",
    needs_fix: "amber",
    blocked: "red",
    stalled: "red",
  }[status] || "";
}

export function statusLabel(status) {
  return String(status || empty).replaceAll("_", " ");
}

export function metaValue(value) {
  return value == null || value === "" ? empty : value;
}

export function formatTime(iso) {
  if (!iso) return empty;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour12: false });
}

export function eventDetail(event) {
  const payload = event.payload || {};
  if (event.event_type === "repair_dispatched") {
    return `attempt ${payload.attempt} - failing {${(payload.failing || []).join(", ")}} -> ${
      payload.repair_assignment_id
    }`;
  }
  if (event.event_type === "contract_escalated") {
    return `${payload.reason ? payload.reason + " " : ""}-> awaiting_human`;
  }
  if (event.event_type === "verification_reported") {
    return `${payload.invariant_key || ""} = ${payload.outcome || ""}`;
  }
  for (const key of [
    "summary",
    "decision_note",
    "reason",
    "response",
    "prompt",
    "outcome",
    "intervention_kind",
  ]) {
    if (payload[key] != null && payload[key] !== "") return String(payload[key]);
  }
  return "";
}

export function restoreHorizontalScroll(node, left) {
  if (!node) return;
  node.scrollLeft = Math.min(left, Math.max(0, node.scrollWidth - node.clientWidth));
}

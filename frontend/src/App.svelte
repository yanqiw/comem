<script>
  import { onMount, tick } from "svelte";

  import {
    attentionLabel,
    attentionSortValue,
    badgeColor,
    briefFreshnessLabel,
    empty,
    eventDetail,
    formatTime,
    metaValue,
    queueActiveTotal,
    queueAttentionTotal,
    queueEntries,
    queueTotal,
    restoreHorizontalScroll,
    statusLabel,
    statusTone,
  } from "./ui.js";

  const teamKey = "cm.team";
  const statusOrder = [
    "needs_fix",
    "awaiting_review",
    "awaiting_approval",
    "awaiting_human",
    "blocked",
    "stalled",
    "running",
    "claimed",
    "ready",
    "accepted",
    "rejected",
    "superseded",
    "cancelled",
    "archived",
  ];
  const attentionStatuses = new Set([
    "needs_fix",
    "awaiting_review",
    "awaiting_approval",
    "awaiting_human",
    "blocked",
    "stalled",
    "running",
    "claimed",
    "ready",
  ]);

  let team = localStorage.getItem(teamKey) || "default";
  let teams = [];
  let auto = true;
  let timer = null;
  let routeLoadGeneration = 0;
  let route = { name: "dashboard", id: null };
  let loading = true;
  let error = "";
  let updated = "pending";
  let versionText = "";
  let versionTitle = "coordination-memory-mcp package version";
  let boardEl;

  let board = null;
  let attentionBoard = null;
  let governance = null;
  let workspaces = [];
  let workspaceDetail = null;
  let contractDetail = null;
  let assignmentDetail = null;
  let runDetail = null;
  let briefDetail = null;

  const isDashboardRoute = () => route.name === "dashboard" || route.name === "team";

  async function getJSON(path) {
    const response = await fetch(path);
    if (!response.ok) {
      let message = response.statusText;
      try {
        message = (await response.json()).error || message;
      } catch (_err) {
        message = response.statusText;
      }
      throw new Error(message);
    }
    return response.json();
  }

  async function postJSON(path) {
    const response = await fetch(path, { method: "POST" });
    if (!response.ok) {
      let message = response.statusText;
      try {
        message = (await response.json()).error || message;
      } catch (_err) {
        message = response.statusText;
      }
      throw new Error(message);
    }
    return response.json();
  }

  async function getOptionalJSON(path) {
    const response = await fetch(path);
    if (response.status === 400 || response.status === 404) return null;
    if (!response.ok) {
      let message = response.statusText;
      try {
        message = (await response.json()).error || message;
      } catch (_err) {
        message = response.statusText;
      }
      throw new Error(message);
    }
    return response.json();
  }

  function parseRoute() {
    const hash = location.hash || "#/";
    const routes = [
      [/^#\/$/, () => ({ name: "dashboard", id: null })],
      [/^#\/teams\/(.+)$/, (match) => ({ name: "team", id: decodeURIComponent(match[1]) })],
      [/^#\/workspaces$/, () => ({ name: "workspaces", id: null })],
      [/^#\/workspaces\/(.+)$/, (match) => ({ name: "workspace", id: decodeURIComponent(match[1]) })],
      [/^#\/contracts\/(.+)$/, (match) => ({ name: "contract", id: decodeURIComponent(match[1]) })],
      [/^#\/assignments\/(.+)$/, (match) => ({
        name: "assignment",
        id: decodeURIComponent(match[1]),
      })],
      [/^#\/runs\/(.+)$/, (match) => ({ name: "run", id: decodeURIComponent(match[1]) })],
    ];
    for (const [pattern, makeRoute] of routes) {
      const match = hash.match(pattern);
      if (match) return makeRoute(match);
    }
    return { name: "dashboard", id: null };
  }

  function setSelectedTeam(teamId) {
    team = teamId || "default";
    localStorage.setItem(teamKey, team);
  }

  function scheduleAuto() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    if (isDashboardRoute() && auto) timer = setInterval(autoTick, 5000);
  }

  async function loadDashboard(teamId, generation) {
    setSelectedTeam(teamId);
    const [nextBoard, nextAttention, nextGovernance] = await Promise.all([
      getJSON("/api/board?team_id=" + encodeURIComponent(teamId)),
      getJSON("/api/attention?team_id=" + encodeURIComponent(teamId)),
      getJSON("/api/governance?team_id=" + encodeURIComponent(teamId)),
    ]);
    if (generation !== routeLoadGeneration) return;
    board = nextBoard;
    attentionBoard = nextAttention;
    governance = nextGovernance;
  }

  async function loadCurrentRoute({ silent = false } = {}) {
    const generation = ++routeLoadGeneration;
    const isCurrent = () => generation === routeLoadGeneration;
    const nextRoute = parseRoute();
    if (!silent) loading = true;
    error = "";
    route = nextRoute;
    try {
      if (nextRoute.name === "dashboard") await loadDashboard(team, generation);
      else if (nextRoute.name === "team") await loadDashboard(nextRoute.id, generation);
      else if (nextRoute.name === "workspaces") {
        const nextWorkspaces = await getJSON("/api/workspaces");
        if (!isCurrent()) return false;
        workspaces = nextWorkspaces;
      } else if (nextRoute.name === "workspace") {
        const nextWorkspaceDetail = await getJSON(
          "/api/workspaces/" + encodeURIComponent(nextRoute.id),
        );
        if (!isCurrent()) return false;
        workspaceDetail = nextWorkspaceDetail;
      } else if (nextRoute.name === "contract") {
        const nextContractDetail = await getJSON(
          "/api/contracts/" + encodeURIComponent(nextRoute.id),
        );
        if (!isCurrent()) return false;
        contractDetail = nextContractDetail;
      } else if (nextRoute.name === "assignment") {
        const nextAssignmentDetail = await getJSON(
          "/api/assignments/" + encodeURIComponent(nextRoute.id),
        );
        const nextBriefDetail = nextAssignmentDetail.assignment?.active_run_id
          ? await getOptionalJSON(
              "/api/runs/" +
                encodeURIComponent(nextAssignmentDetail.assignment.active_run_id) +
                "/brief",
            )
          : null;
        if (!isCurrent()) return false;
        assignmentDetail = nextAssignmentDetail;
        briefDetail = nextBriefDetail;
      } else if (nextRoute.name === "run") {
        const [nextRunDetail, nextBriefDetail] = await Promise.all([
          getJSON("/api/runs/" + encodeURIComponent(nextRoute.id)),
          getOptionalJSON("/api/runs/" + encodeURIComponent(nextRoute.id) + "/brief"),
        ]);
        if (!isCurrent()) return false;
        runDetail = nextRunDetail;
        briefDetail = nextBriefDetail;
      }
      if (!isCurrent()) return false;
      updated = "updated " + new Date().toLocaleTimeString();
      return true;
    } catch (err) {
      if (!isCurrent()) return false;
      error = err.message || String(err);
      return false;
    } finally {
      if (isCurrent()) {
        loading = false;
        scheduleAuto();
      }
    }
  }

  async function autoTick() {
    if (document.hidden) return;
    const selection = String(window.getSelection ? window.getSelection() : "");
    if (selection) return;
    const y = window.scrollY;
    const boardLeft = boardEl ? boardEl.scrollLeft : 0;
    const loaded = await loadCurrentRoute({ silent: true });
    if (!loaded) return;
    await tick();
    window.scrollTo(0, y);
    restoreHorizontalScroll(boardEl, boardLeft);
  }

  async function loadTeams() {
    try {
      teams = await getJSON("/api/teams");
    } catch (_err) {
      teams = [];
    }
  }

  async function loadVersion() {
    try {
      const version = await getJSON("/api/version");
      versionText = "v" + version.version;
      versionTitle =
        "coordination-memory-mcp " +
        version.version +
        (version.build ? ", static build " + version.build : "");
    } catch (_err) {
      versionText = "";
    }
  }

  function handleTeamChange(event) {
    setSelectedTeam(event.target.value);
    if ((location.hash || "#/") === "#/") loadCurrentRoute();
    else location.hash = "#/";
  }

  async function archiveWorkspace(id) {
    if (!window.confirm("Archive workspace " + id + "?")) return;
    try {
      await postJSON("/api/workspaces/" + encodeURIComponent(id) + "/archive");
      await loadCurrentRoute();
    } catch (err) {
      error = err.message || String(err);
    }
  }

  function teamDashboardHref(teamId) {
    return "#/teams/" + encodeURIComponent(teamId);
  }

  function statusSortValue(status) {
    const index = statusOrder.indexOf(status);
    return index === -1 ? statusOrder.length + 1 : index;
  }

  function sortedStatusKeys(counts) {
    return Object.keys(counts || {}).sort(
      (a, b) => statusSortValue(a) - statusSortValue(b) || a.localeCompare(b),
    );
  }

  function assignmentCountTotal(counts) {
    return Object.values(counts || {}).reduce((sum, n) => sum + Number(n || 0), 0);
  }

  function attentionCount(counts) {
    return Object.entries(counts || {}).reduce(
      (sum, [status, n]) => sum + (attentionStatuses.has(status) ? Number(n || 0) : 0),
      0,
    );
  }

  function teamStatusSummary(teamRow, limit = 99) {
    const counts = teamRow.assignment_counts || {};
    const keys = sortedStatusKeys(counts);
    if (!keys.length) return "0 assignments";
    const shown = keys.slice(0, limit).map((key) => statusLabel(key) + " " + counts[key]);
    if (keys.length > shown.length) shown.push("+" + (keys.length - shown.length) + " more");
    return shown.join(" / ");
  }

  function sortedTeams(items) {
    return (items || []).slice().sort(
      (a, b) =>
        attentionCount(b.assignment_counts) - attentionCount(a.assignment_counts) ||
        assignmentCountTotal(b.assignment_counts) - assignmentCountTotal(a.assignment_counts) ||
        String(a.name || a.team_id).localeCompare(String(b.name || b.team_id)),
    );
  }

  function workspaceSummary(items) {
    return (items || []).reduce(
      (acc, workspace) => {
        acc.teams += Number(workspace.team_count || 0);
        acc.assignments += Number(workspace.assignment_total || 0);
        acc.attention += attentionCount(workspace.assignment_counts);
        if (workspace.status === "active") acc.active += 1;
        return acc;
      },
      { active: 0, teams: 0, assignments: 0, attention: 0 },
    );
  }

  function presentFields(pairs) {
    return pairs.filter(([, value]) => value != null && value !== "");
  }

  function specEntries(spec) {
    if (spec == null || typeof spec !== "object" || Array.isArray(spec)) return null;
    return Object.entries(spec).map(([key, value]) => [
      key,
      value != null && typeof value === "object" ? JSON.stringify(value) : String(value),
    ]);
  }

  function jsonValue(value) {
    return value == null ? empty : JSON.stringify(value);
  }

  function sortedAttentionItems(items) {
    return (items || [])
      .filter((item) => item.level !== "green")
      .slice()
      .sort(
        (a, b) =>
          attentionSortValue(a.level) - attentionSortValue(b.level) ||
          Number(a.sequence || 0) - Number(b.sequence || 0),
      );
  }

  function humanBriefRows(detail) {
    const brief = detail?.brief || {};
    return [
      ["schema_version", brief.schema_version],
      ["current_goal", brief.current_goal],
      ["current_stage", brief.current_stage],
      ["recent_progress", jsonValue(brief.recent_progress)],
      ["decisions_and_risks", jsonValue(brief.decisions_and_risks)],
      ["human_intervention", jsonValue(brief.human_intervention)],
      ["next_steps", jsonValue(brief.next_steps)],
      ["context_refs", jsonValue(brief.context_refs)],
    ];
  }

  function contractCards(cards, attention) {
    return (cards || []).map((card) => ({ ...card, attention }));
  }

  function contractRequired(detail) {
    return (detail?.invariants || []).filter((item) => item.required);
  }

  function contractFailing(detail) {
    return new Set(detail?.failing_required || []);
  }

  function contractBlockers(detail) {
    return (detail?.deviations || []).filter(
      (item) => item.disposition === "blocker" && item.status === "open",
    );
  }

  function contractHint(status) {
    return {
      awaiting_human:
        "acceptor may waive_deviation the blocker, or Integrator may reopen_contract",
      awaiting_acceptor: "independent acceptor may accept_contract",
      repair_ready: "repair dispatched; will re-evaluate",
    }[status];
  }

  onMount(() => {
    loadVersion();
    loadTeams();
    loadCurrentRoute();
    window.addEventListener("hashchange", loadCurrentRoute);
    return () => {
      window.removeEventListener("hashchange", loadCurrentRoute);
      if (timer) clearInterval(timer);
    };
  });
</script>

<header class="topbar">
  <strong class="brand">Coordination Memory</strong>
  <nav class="nav global-nav" aria-label="Global">
    <a href="#/workspaces">Workspaces</a>
  </nav>
  <div class="controls">
    <span id="version" class="muted" title={versionTitle}>{versionText}</span>
    <div class="team-scope">
      <label>
        team
        <select id="team-switcher" bind:value={team} onchange={handleTeamChange}>
          {#each teams as item (item.team_id)}
            <option value={item.team_id}>{item.name || item.team_id}</option>
          {/each}
        </select>
      </label>
      <a class="button-link" href="#/">Dashboard</a>
    </div>
    <span id="updated" class="muted">{updated}</span>
    <label class="auto"><input type="checkbox" id="auto" bind:checked={auto} onchange={scheduleAuto}> auto 5s</label>
  </div>
</header>

<main id="view">
  {#if error}
    <div>
      <p class="err">Couldn't load: {error}</p>
      <button type="button" onclick={() => loadCurrentRoute()}>Retry</button>
    </div>
  {:else if loading}
    <p class="muted">Loading...</p>
  {:else if route.name === "dashboard" || route.name === "team"}
    {@const laneData = board?.lanes || {}}
    {@const counts = governance?.counts || {}}
    {@const humanAttentionCounts = attentionBoard?.counts || {}}
    {@const humanAttentionItems = sortedAttentionItems(attentionBoard?.items)}
    {@const attentionAssignments = queueAttentionTotal(laneData)}
    {@const blockers = Number(counts.open_blockers || 0)}
    {@const healthTone = blockers ? "critical" : attentionAssignments ? "warn" : "success"}
    {@const healthText = blockers ? "Blocked" : attentionAssignments ? "Needs attention" : "Clear"}
    <div class="dashboard-shell">
      <section class="dashboard-hero">
        <div class="dashboard-hero-main">
          <div class="dashboard-kicker">
            {route.name === "team" ? "Team dashboard" : "Selected team dashboard"}
          </div>
          <h1>{board?.team?.name || team}</h1>
          <div class="dashboard-meta">
            <span class="meta-chip">id {team}</span>
            {#if board?.team?.workspace_id}<span class="meta-chip">workspace {board.team.workspace_id}</span>{/if}
            {#if board?.team?.owner_actor_id}<span class="meta-chip">owner {board.team.owner_actor_id}</span>{/if}
            {#if board?.team?.status}<span class="meta-chip">status {board.team.status}</span>{/if}
          </div>
        </div>
        <div class={"dashboard-health " + healthTone}>
          <span class="health-label">Board health</span>
          <strong>{healthText}</strong>
          <span>{attentionAssignments} attention items</span>
        </div>
      </section>

      <section class="attention-console" aria-labelledby="human-attention-title">
        <div class="attention-console-head">
          <div>
            <div class="dashboard-kicker">Human Attention</div>
            <h2 id="human-attention-title">Needs your attention</h2>
          </div>
          <div class="attention-counts" aria-label="Attention counts">
            <span class="attention-count critical">Red {humanAttentionCounts.red || 0}</span>
            <span class="attention-count warn">Yellow {humanAttentionCounts.yellow || 0}</span>
            <span class="attention-count resolved">Green {humanAttentionCounts.green || 0}</span>
          </div>
        </div>
        {#if humanAttentionItems.length}
          <div class="attention-list">
            {#each humanAttentionItems as item (item.event_id)}
              <article class={"attention-item attention-item-" + item.level}>
                <div class="attention-item-head">
                  <strong>{attentionLabel(item.level)}</strong>
                  <span class={"badge " + (item.level === "red" ? "red" : "amber")}>{item.reason_code || statusLabel(item.level)}</span>
                </div>
                <p class="attention-reason">{item.why_now}</p>
                {#if item.level === "red"}
                  <div class="decision-packet">
                    <strong>Decision Packet</strong>
                    <div>{item.decision_packet?.summary || item.why_now}</div>
                    {#if item.decision_packet?.options}
                      <div class="muted">Options: {jsonValue(item.decision_packet.options)}</div>
                    {/if}
                  </div>
                {/if}
                <div class="attention-action"><span>Recommended action</span> {item.recommended_action}</div>
                <div class="attention-links">
                  <a href={"#/runs/" + encodeURIComponent(item.run_id)}>View Run</a>
                  <a href={"#/assignments/" + encodeURIComponent(item.assignment_id)}>View Assignment</a>
                </div>
              </article>
            {/each}
          </div>
        {:else}
          <div class="empty-state attention-empty">No items currently require your attention.</div>
        {/if}
      </section>

      <div class="dashboard-summary">
        <div class="dashboard-stat">
          <div class="dashboard-stat-label">Assignments</div>
          <div class="dashboard-stat-value">{queueTotal(laneData)}</div>
          <div class="dashboard-stat-note">Across all queues</div>
        </div>
        <div class={"dashboard-stat " + (attentionAssignments ? "warn" : "success")}>
          <div class="dashboard-stat-label">Needs attention</div>
          <div class="dashboard-stat-value">{attentionAssignments}</div>
          <div class="dashboard-stat-note">{attentionAssignments ? "Review or repair required" : "No urgent work"}</div>
        </div>
        <div class="dashboard-stat">
          <div class="dashboard-stat-label">Active work</div>
          <div class="dashboard-stat-value">{queueActiveTotal(laneData)}</div>
          <div class="dashboard-stat-note">Running, ready, or review</div>
        </div>
        <div class={"dashboard-stat " + (counts.open_blockers ? "critical" : "")}>
          <div class="dashboard-stat-label">Contracts</div>
          <div class="dashboard-stat-value">{counts.contracts || 0}</div>
          <div class="dashboard-stat-note">{counts.open_blockers || 0} open blockers</div>
        </div>
      </div>

      <div class="section-heading">
        <div>
          <h2>Assignment board</h2>
          <p class="muted">{queueTotal(laneData)} assignments across {queueEntries(laneData).length} queues</p>
        </div>
      </div>
      <div class="board product-board" bind:this={boardEl}>
        {#each queueEntries(laneData) as [lane, items] (lane)}
          <section class={"lane lane-" + statusTone(lane)}>
            <div class="lane-title">
              <div>
                <h3>{statusLabel(lane)}</h3>
                <span>{items.length ? "Queue is live" : "No current work"}</span>
              </div>
              <span class="lane-count">{items.length}</span>
            </div>
            <div class="lane-items">
              {#each items as assignment (assignment.assignment_id)}
                <article class={"assignment assignment-" + statusTone(assignment.status)}>
                  <div class="a-top">
                    <a class="assignment-title" href={"#/assignments/" + encodeURIComponent(assignment.assignment_id)}>
                      {assignment.title || assignment.assignment_id}
                    </a>
                    <span class={"badge " + badgeColor(assignment.status)}>{statusLabel(assignment.status)}</span>
                  </div>
                  <div class="a-id" title={assignment.assignment_id}>{assignment.assignment_id}</div>
                  <div class="assignment-meta">
                    {#if assignment.claimed_by}<span>@{assignment.claimed_by}</span>{/if}
                    {#if assignment.priority != null}<span>P{assignment.priority}</span>{/if}
                    {#if assignment.revision != null}<span>rev {assignment.revision}</span>{/if}
                    {#if assignment.workspace_id}<span>{assignment.workspace_id}</span>{/if}
                  </div>
                  {#if assignment.contract_id}
                    <a class="contract-link" href={"#/contracts/" + encodeURIComponent(assignment.contract_id)}>View contract</a>
                  {/if}
                </article>
              {:else}
                <div class="empty-state">No assignments</div>
              {/each}
            </div>
          </section>
        {/each}
      </div>

      <div class="section-heading">
        <div>
          <h2>Acceptance contracts</h2>
          <p class="muted">{counts.contracts ? "Governed goals and independent sign-off state" : "No governed goals yet"}</p>
        </div>
      </div>
      <div class="stat-strip contract-summary">
        <div class="stat"><div class="n">{counts.contracts || 0}</div><div class="l">contracts</div></div>
        <div class="stat alarm"><div class="n">{counts.awaiting_human || 0}</div><div class="l">awaiting human</div></div>
        <div class="stat warn"><div class="n">{counts.open_blockers || 0}</div><div class="l">open blockers</div></div>
        <div class="stat"><div class="n">{counts.in_repair || 0}</div><div class="l">in repair</div></div>
        <div class="stat"><div class="n">{counts.accepted || 0}</div><div class="l">accepted</div></div>
      </div>

      {#if !(counts.contracts || 0)}
        <div class="empty-state contract-empty">No acceptance contracts yet. Governed goals will appear here.</div>
      {:else if !(governance?.needs_attention || []).length && !(governance?.in_flight || []).length}
        <div class="empty-state contract-empty">Nothing needs attention.</div>
      {:else}
        {#if (governance?.needs_attention || []).length}
          <div class="section-heading">
            <div>
              <h2>Needs attention</h2>
              <p class="muted">Contracts waiting for human or repair action</p>
            </div>
          </div>
          <div class="cards">
            {#each contractCards(governance.needs_attention, true) as card (card.contract_id)}
              <div class="ccard attention">
                <div class="contract-title"><a href={"#/contracts/" + encodeURIComponent(card.contract_id)}>{card.title}</a></div>
                <div class="a-id" title={card.contract_id}>{card.contract_id}</div>
                <div class="contract-status"><span class={"badge " + badgeColor(card.status)}>{statusLabel(card.status)}</span></div>
                <div class="contract-meta">
                  <span>probes {card.probes_passed}/{card.probes_total}</span>
                  <span>loop {card.repair_attempt}/{card.max_repair_attempts}</span>
                  {#if card.acceptor_actor_id}<span>acceptor {card.acceptor_actor_id}</span>{/if}
                </div>
                {#each card.open_blockers || [] as blocker}
                  <div class="blocker-row"><span class="badge amber">blocker: {blocker}</span></div>
                {/each}
                {#if card.next_action_hint}<div class="hint">Next: {card.next_action_hint}</div>{/if}
              </div>
            {/each}
          </div>
        {/if}
        {#if (governance?.in_flight || []).length}
          <div class="section-heading">
            <div>
              <h2>In flight</h2>
              <p class="muted">Contracts currently verifying or waiting for acceptance</p>
            </div>
          </div>
          <div class="cards">
            {#each contractCards(governance.in_flight, false) as card (card.contract_id)}
              <div class="ccard">
                <div class="contract-title"><a href={"#/contracts/" + encodeURIComponent(card.contract_id)}>{card.title}</a></div>
                <div class="a-id" title={card.contract_id}>{card.contract_id}</div>
                <div class="contract-status"><span class={"badge " + badgeColor(card.status)}>{statusLabel(card.status)}</span></div>
                <div class="contract-meta">
                  <span>probes {card.probes_passed}/{card.probes_total}</span>
                  <span>loop {card.repair_attempt}/{card.max_repair_attempts}</span>
                  {#if card.acceptor_actor_id}<span>acceptor {card.acceptor_actor_id}</span>{/if}
                </div>
                {#if card.next_action_hint}<div class="hint">Next: {card.next_action_hint}</div>{/if}
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  {:else if route.name === "workspaces"}
    {@const totals = workspaceSummary(workspaces)}
    <div>
      <div class="toolbar workspace-toolbar">
        <div>
          <strong class="page-title">Workspaces</strong>
          <div class="muted">{workspaces.length} total</div>
        </div>
      </div>
      <div class="workspace-summary">
        <div class="summary-tile"><div class="n">{workspaces.length}</div><div class="l">Workspaces</div></div>
        <div class="summary-tile"><div class="n">{totals.active}</div><div class="l">Active</div></div>
        <div class="summary-tile"><div class="n">{totals.teams}</div><div class="l">Teams</div></div>
        <div class="summary-tile"><div class="n">{totals.assignments}</div><div class="l">Assignments</div></div>
        <div class={"summary-tile " + (totals.attention ? "attention" : "")}>
          <div class="n">{totals.attention}</div><div class="l">Need attention</div>
        </div>
      </div>
      <div class="workspace-grid workspace-list">
        {#each workspaces as workspace (workspace.workspace_id)}
          {@const attention = attentionCount(workspace.assignment_counts)}
          <div class={"workspace-card " + (workspace.status === "archived" ? "archived " : "") + (attention ? "needs-attention" : "")}>
            <div class="workspace-main">
              <div class="workspace-card-head">
                <div class="workspace-title-block">
                  <a class="workspace-title" href={"#/workspaces/" + encodeURIComponent(workspace.workspace_id)}>{workspace.name || workspace.workspace_id}</a>
                  <div class="a-id" title={workspace.workspace_id}>{workspace.workspace_id}</div>
                </div>
                <span class={"badge " + badgeColor(workspace.status)}>{statusLabel(workspace.status)}</span>
              </div>
              <div class="workspace-metrics">
                <div class="workspace-metric"><span>Teams</span><b>{workspace.team_count || 0}</b></div>
                <div class="workspace-metric"><span>Assignments</span><b>{workspace.assignment_total || 0}</b></div>
                <div class="workspace-metric" title={workspace.default_branch || empty}><span>Branch</span><b>{workspace.default_branch || empty}</b></div>
              </div>
              {#if workspace.repo_root}<div class="repo-path" title={workspace.repo_root}>{workspace.repo_root}</div>{/if}
              <div class="chips">
                {#each sortedStatusKeys(workspace.assignment_counts) as key}
                  <span class={"badge " + badgeColor(key)}>{statusLabel(key)} {workspace.assignment_counts[key]}</span>
                {:else}
                  <span class="muted">No assignments</span>
                {/each}
              </div>
            </div>
            <div class="workspace-team-panel">
              {#if (workspace.teams || []).length}
                <div class="team-list">
                  <div class="team-list-head"><span>Teams</span><span class="muted">{workspace.teams.length} total</span></div>
                  <div class="team-list-body">
                    {#each sortedTeams(workspace.teams) as item (item.team_id)}
                      <div class="team-row">
                        <a class="team-name team-link" href={teamDashboardHref(item.team_id)} title={item.team_id}>{item.name || item.team_id}</a>
                        <span class="muted">{teamStatusSummary(item)}</span>
                      </div>
                    {/each}
                  </div>
                </div>
              {:else}
                <div class="team-empty muted">No teams</div>
              {/if}
            </div>
          </div>
        {:else}
          <p class="muted">No workspaces</p>
        {/each}
      </div>
    </div>
  {:else if route.name === "workspace" && workspaceDetail}
    {@const workspace = workspaceDetail.workspace}
    <div>
      <div class="toolbar">
        <div>
          <div class="crumb">Workspaces / {workspace.workspace_id}</div>
          <strong style="font-size:16px">{workspace.name || workspace.workspace_id}</strong>
          <span class={"badge " + badgeColor(workspace.status)}>{statusLabel(workspace.status)}</span>
        </div>
        <div class="actions">
          <a href="#/workspaces">Workspaces</a>
          {#if workspace.status !== "archived" && !(workspace.metadata && workspace.metadata.virtual)}
            <button class="danger" type="button" onclick={() => archiveWorkspace(workspace.workspace_id)}>Archive workspace</button>
          {/if}
        </div>
      </div>
      <div class="stat-strip">
        <div class="stat"><div class="n">{workspaceDetail.assignment_total || 0}</div><div class="l">assignments</div></div>
        {#each sortedStatusKeys(workspaceDetail.assignment_counts) as key}
          <div class="stat"><div class="n">{workspaceDetail.assignment_counts[key]}</div><div class="l">{statusLabel(key)}</div></div>
        {/each}
      </div>
      <div class="section-label">Workspace detail</div>
      <table>
        <tbody>
          <tr><th>field</th><th>value</th></tr>
          {#each presentFields([
            ["workspace_id", workspace.workspace_id],
            ["name", workspace.name],
            ["status", workspace.status],
            ["repo_root", workspace.repo_root],
            ["default_branch", workspace.default_branch],
            ["created_at", workspace.created_at],
            ["updated_at", workspace.updated_at],
          ]) as [label, value]}
            <tr><td>{label}</td><td>{value}</td></tr>
          {/each}
        </tbody>
      </table>
      <div class="section-label">Teams</div>
      {#if (workspaceDetail.teams || []).length}
        <table>
          <tbody>
            <tr><th>team</th><th>name</th><th>status</th><th>assignments</th><th>status counts</th><th>owner</th><th>phase</th></tr>
            {#each workspaceDetail.teams as item (item.team_id)}
              <tr>
                <td><a class="team-link" href={teamDashboardHref(item.team_id)}>{item.team_id}</a></td>
                <td>{item.name || empty}</td>
                <td>{item.status || empty}</td>
                <td>{item.assignment_total ?? 0}</td>
                <td>{teamStatusSummary(item)}</td>
                <td>{item.owner_actor_id || empty}</td>
                <td>{item.phase_key || empty}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">No teams</p>
      {/if}
      <div class="section-label">Assignments</div>
      {#if (workspaceDetail.assignments || []).length}
        <table>
          <tbody>
            <tr><th>assignment</th><th>status</th><th>team</th><th>claimed by</th><th>revision</th></tr>
            {#each workspaceDetail.assignments as assignment (assignment.assignment_id)}
              <tr>
                <td>
                  <a href={"#/assignments/" + encodeURIComponent(assignment.assignment_id)}>{assignment.title || assignment.assignment_id}</a>
                  <div class="a-id" title={assignment.assignment_id}>{assignment.assignment_id}</div>
                </td>
                <td><span class={"badge " + badgeColor(assignment.status)}>{statusLabel(assignment.status)}</span></td>
                <td>{assignment.team_id || empty}</td>
                <td>{assignment.claimed_by || empty}</td>
                <td>{assignment.revision ?? empty}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">No assignments</p>
      {/if}
    </div>
  {:else if route.name === "contract" && contractDetail}
    {@const contract = contractDetail.contract}
    {@const required = contractRequired(contractDetail)}
    {@const failing = contractFailing(contractDetail)}
    {@const passed = required.filter((item) => !failing.has(item.key)).length}
    {@const blockers = contractBlockers(contractDetail)}
    <div>
      <div class="crumb">Dashboard / Contracts / {contract.title}</div>
      <div>
        <strong style="font-size:16px">{contract.title}</strong>
        <span class={"badge " + badgeColor(contract.status)}>{statusLabel(contract.status)}</span>
        <span class="muted"> rev {contract.revision}{contract.acceptor_actor_id ? ", acceptor: " + contract.acceptor_actor_id : ""}</span>
      </div>
      <div class="muted" style="margin:6px 0 12px">Goal: {contract.goal_statement}</div>
      <div class="stepper">
        <div class="step"><div>Seal {contract.sealed_at ? "pass" : "pending"}</div><div class="muted">{required.length} invariants, frozen</div></div>
        <div class="step"><div>Evaluate {passed === required.length && !blockers.length ? "pass" : "needs work"}</div><div class="muted">{passed}/{required.length} green, {blockers.length} blocker, loop {contract.repair_attempt}/{contract.max_repair_attempts}</div></div>
        <div class="step"><div>Accept {contract.status === "accepted" ? "pass" : "pending"}</div><div class="muted">{contract.status === "accepted" ? "accepted" : "pending gate"}</div></div>
      </div>
      <div class="section-label">Invariants</div>
      <table>
        <tbody>
          <tr><th>key</th><th>kind</th><th>flags</th><th>latest</th><th>evidence</th></tr>
          {#each contractDetail.invariants || [] as invariant (invariant.key)}
            <tr>
              <td>{invariant.key}</td>
              <td>{invariant.probe_kind}</td>
              <td>{[invariant.is_negative ? "deny" : null, invariant.is_second_instance ? "2nd-instance" : null, invariant.required ? "required" : "optional"].filter(Boolean).join(" / ")}</td>
              <td>{(contractDetail.latest_verifications || {})[invariant.key] || empty}</td>
              <td>
                {#if specEntries(invariant.probe_spec)}
                  <div class="kvs">
                    {#each specEntries(invariant.probe_spec) as [key, value]}
                      <span class="kv"><b>{key}</b> {value}</span>
                    {/each}
                  </div>
                {:else}
                  <span class="muted">{jsonValue(invariant.probe_spec)}</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="section-label">Deviation register</div>
      {#if (contractDetail.deviations || []).length}
        <table>
          <tbody>
            <tr><th>title</th><th>disposition</th><th>status</th><th>raised by</th></tr>
            {#each contractDetail.deviations as deviation}
              <tr><td>{deviation.title}</td><td>{deviation.disposition}</td><td>{deviation.status}</td><td>{deviation.raised_by_actor_id}</td></tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">No deviations</p>
      {/if}
      <div class="section-label">Repair loop & events</div>
      {#if (contractDetail.events || []).length}
        <div class="events">
          {#each contractDetail.events as event (event.event_id)}
            <div class="event">
              <time class="ev-time" title={event.created_at || ""}>{formatTime(event.created_at)}</time>
              <div class="ev-main">
                <div class="ev-head"><span class="ev-type">{event.event_type}</span>{#if event.status}<span class="ev-meta">{event.status}</span>{/if}{#if event.actor_id}<span class="ev-meta">{event.actor_id}</span>{/if}</div>
                {#if eventDetail(event)}<div class="ev-detail">{eventDetail(event)}</div>{/if}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted">No events</p>
      {/if}
      <div class="section-label">Bound assignments</div>
      <div class="timeline">
        {#each contractDetail.bound_assignments || [] as assignment}
          <div><a href={"#/assignments/" + encodeURIComponent(assignment.assignment_id)}>{assignment.assignment_id}</a> / {assignment.status}</div>
        {/each}
      </div>
      {#if contractHint(contract.status)}
        <div class="callout">Next (read-only): {contractHint(contract.status)}. The dashboard does not act.</div>
      {/if}
    </div>
  {:else if route.name === "assignment" && assignmentDetail}
    {@const assignment = assignmentDetail.assignment || {}}
    <div>
      <div class="crumb">Dashboard / Assignments / {route.id}</div>
      <div>
        <strong style="font-size:16px">{assignment.title || route.id}</strong>
        <span class={"badge " + badgeColor(assignment.status)}>{statusLabel(assignment.status)}</span>
        <span class="muted"> {assignment.assignment_id}</span>
        {#if assignment.contract_id}<a href={"#/contracts/" + encodeURIComponent(assignment.contract_id)}>Contract</a>{/if}
      </div>
      <div class="section-label">Summary</div>
      <table>
        <tbody>
          <tr><th>field</th><th>value</th></tr>
          {#each presentFields([
            ["status", assignment.status],
            ["revision", assignment.revision != null ? String(assignment.revision) : null],
            ["claimed_by", assignment.claimed_by],
            ["team_id", assignment.team_id],
            ["workspace_id", assignment.workspace_id],
            ["priority", assignment.priority != null ? String(assignment.priority) : null],
            ["lease_expires_at", assignment.lease_expires_at],
            ["created_at", assignment.created_at],
            ["updated_at", assignment.updated_at],
            ["completed_at", assignment.completed_at],
            ["active_run_id", assignment.active_run_id],
          ]) as [label, value]}
            <tr><td>{label}</td><td>{value}</td></tr>
          {/each}
        </tbody>
      </table>
      {#if (assignment.acceptance_criteria || []).length}
        <div class="section-label">Acceptance criteria</div>
        <ul class="criteria">
          {#each assignment.acceptance_criteria as criterion}
            <li>{criterion}</li>
          {/each}
        </ul>
      {/if}
      {#if (assignment.allowed_paths || []).length}
        <div class="section-label">Allowed paths</div>
        <div class="chips">
          {#each assignment.allowed_paths as path}
            <code class="chip">{path}</code>
          {/each}
        </div>
      {/if}
      <div class="section-label">Human Resume Brief</div>
      {#if briefDetail}
        <section class="human-brief">
          <div class="human-brief-head">
            <div>
              <strong>Latest Brief</strong>
              <div class="muted">Updated {briefDetail.updated_at || empty}</div>
            </div>
            <span class={"badge " + (briefDetail.freshness === "fresh" ? "green" : "amber")}>
              {briefFreshnessLabel(briefDetail.freshness)}
            </span>
          </div>
          <table class="human-brief-table">
            <tbody>
              <tr><th>field</th><th>value</th></tr>
              {#each humanBriefRows(briefDetail) as [label, value]}
                <tr><td>{label}</td><td>{value}</td></tr>
              {/each}
            </tbody>
          </table>
          <div class="human-brief-meta muted">
            source event {briefDetail.source_event_sequence ?? empty} / latest event {briefDetail.latest_event_sequence ?? empty}
          </div>
        </section>
      {:else}
        <div class="empty-state human-brief-empty">No Human Resume Brief yet.</div>
      {/if}
      <div class="section-label">Runs</div>
      {#if (assignmentDetail.runs || []).length}
        <table>
          <tbody>
            <tr><th>attempt</th><th>run_id</th><th>actor_id</th><th>status</th><th>started_at -> ended_at</th><th>branch</th></tr>
            {#each assignmentDetail.runs as run (run.run_id)}
              <tr>
                <td>{run.attempt ?? empty}</td>
                <td><a href={"#/runs/" + encodeURIComponent(run.run_id)}>{run.run_id}</a></td>
                <td>{run.actor_id || empty}</td>
                <td>{run.status || empty}</td>
                <td class="muted">{run.started_at || empty} -> {run.ended_at || empty}</td>
                <td>{run.branch || empty}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">No runs</p>
      {/if}
      <div class="section-label">Events</div>
      {#if (assignmentDetail.events || []).length}
        <div class="events">
          {#each assignmentDetail.events as event (event.event_id)}
            <div class="event">
              <time class="ev-time" title={event.created_at || ""}>{formatTime(event.created_at)}</time>
              <div class="ev-main">
                <div class="ev-head"><span class="ev-type">{event.event_type}</span>{#if event.status}<span class="ev-meta">{event.status}</span>{/if}{#if event.actor_id}<span class="ev-meta">{event.actor_id}</span>{/if}</div>
                {#if eventDetail(event)}<div class="ev-detail">{eventDetail(event)}</div>{/if}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted">No events</p>
      {/if}
      <details><summary>Raw JSON</summary><pre class="timeline">{JSON.stringify(assignmentDetail, null, 2)}</pre></details>
    </div>
  {:else if route.name === "run" && runDetail}
    <div>
      <div class="crumb">Dashboard / Runs / {route.id}</div>
      <div>
        <strong style="font-size:16px">{runDetail.run_id || route.id}</strong>
        <span class={"badge " + badgeColor(runDetail.status)}>{statusLabel(runDetail.status)}</span>
        <span class="muted"> attempt {runDetail.attempt ?? empty} / {runDetail.actor_id || empty}</span>
        {#if runDetail.assignment_id}<a href={"#/assignments/" + encodeURIComponent(runDetail.assignment_id)}>Assignment</a>{/if}
      </div>
      <div class="section-label">Summary</div>
      <table>
        <tbody>
          <tr><th>field</th><th>value</th></tr>
          {#each presentFields([
            ["assignment_id", runDetail.assignment_id],
            ["team_id", runDetail.team_id],
            ["attempt", runDetail.attempt != null ? String(runDetail.attempt) : null],
            ["session_kind", runDetail.session_kind],
            ["session_ref", runDetail.session_ref],
            ["worktree_path", runDetail.worktree_path],
            ["branch", runDetail.branch],
            ["base_commit", runDetail.base_commit],
            ["head_commit", runDetail.head_commit],
            ["resume_of_run_id", runDetail.resume_of_run_id],
            ["lease_expires_at", runDetail.lease_expires_at],
            ["heartbeat_at", runDetail.heartbeat_at],
            ["started_at", runDetail.started_at],
            ["ended_at", runDetail.ended_at],
            ["updated_at", runDetail.updated_at],
          ]) as [label, value]}
            <tr><td>{label}</td><td>{value}</td></tr>
          {/each}
          {#if runDetail.interactive_url}
            <tr><td>interactive_url</td><td><a href={runDetail.interactive_url}>{runDetail.interactive_url}</a></td></tr>
          {/if}
        </tbody>
      </table>
      <div class="section-label">Human Resume Brief</div>
      {#if briefDetail}
        <section class="human-brief">
          <div class="human-brief-head">
            <div>
              <strong>Latest Brief</strong>
              <div class="muted">Updated {briefDetail.updated_at || empty}</div>
            </div>
            <span class={"badge " + (briefDetail.freshness === "fresh" ? "green" : "amber")}>
              {briefFreshnessLabel(briefDetail.freshness)}
            </span>
          </div>
          <table class="human-brief-table">
            <tbody>
              <tr><th>field</th><th>value</th></tr>
              {#each humanBriefRows(briefDetail) as [label, value]}
                <tr><td>{label}</td><td>{value}</td></tr>
              {/each}
            </tbody>
          </table>
          <div class="human-brief-meta muted">
            source event {briefDetail.source_event_sequence ?? empty} / latest event {briefDetail.latest_event_sequence ?? empty}
          </div>
        </section>
      {:else}
        <div class="empty-state human-brief-empty">No Human Resume Brief yet.</div>
      {/if}
      <div class="section-label">Events</div>
      {#if (runDetail.events || []).length}
        <div class="events">
          {#each runDetail.events as event (event.event_id)}
            <div class="event">
              <time class="ev-time" title={event.created_at || ""}>{formatTime(event.created_at)}</time>
              <div class="ev-main">
                <div class="ev-head"><span class="ev-type">{event.event_type}</span>{#if event.status}<span class="ev-meta">{event.status}</span>{/if}{#if event.actor_id}<span class="ev-meta">{event.actor_id}</span>{/if}</div>
                {#if eventDetail(event)}<div class="ev-detail">{eventDetail(event)}</div>{/if}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted">No events</p>
      {/if}
      <details><summary>Raw JSON</summary><pre class="timeline">{JSON.stringify(runDetail, null, 2)}</pre></details>
    </div>
  {/if}
</main>

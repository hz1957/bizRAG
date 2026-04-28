const rawPayloads = {
  health: "",
  overview: "",
  metrics: "",
  files: "",
};

let currentFileInventory = { items: [] };
let currentKbItems = [];
let currentRecentSpans = [];
let currentOverview = null;
let currentAlerts = [];
let currentHealthChecks = [];
let currentKbActivity = [];
let currentOpsTab = "overview";

const OPS_TABS = new Set(["overview", "activity", "query", "files"]);
const QUERY_KB_STORAGE_KEY = "bizrag.ops.queryKbId";

function loadPreferredQueryKb() {
  try {
    return window.localStorage?.getItem(QUERY_KB_STORAGE_KEY) || "";
  } catch (_err) {
    return "";
  }
}

function savePreferredQueryKb(value) {
  try {
    if (!value) {
      window.localStorage?.removeItem(QUERY_KB_STORAGE_KEY);
      return;
    }
    window.localStorage?.setItem(QUERY_KB_STORAGE_KEY, String(value));
  } catch (_err) {
  }
}

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function badgeClass(status) {
  return `status-${status || "idle"}`;
}

function titleCase(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function compact(value, limit = 72) {
  const text = String(value ?? "");
  return text.length <= limit ? text : text.slice(0, limit - 1) + "…";
}

function formatDuration(value) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) {
    return "0 ms";
  }
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${ms.toFixed(1)} ms`;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = bytes;
  let idx = 0;
  while (current >= 1024 && idx < units.length - 1) {
    current /= 1024;
    idx += 1;
  }
  const digits = idx === 0 ? 0 : current >= 10 ? 1 : 2;
  return `${current.toFixed(digits)} ${units[idx]}`;
}

function formatAlertValue(item) {
  const ruleId = String(item?.rule_id || "");
  if (ruleId === "retrieve_latency_high" || ruleId === "extract_latency_high") {
    const ms = Number(item?.value || 0);
    if (!Number.isFinite(ms) || ms <= 0) {
      return "0 s";
    }
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return String(item?.value ?? "");
}

function formatTs(value) {
  const text = String(value || "");
  if (!text) return "";
  return text.replace("T", " ").replace("+00:00", "Z");
}

function formatAgeSeconds(value) {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "just now";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  if (seconds < 86400) {
    return `${(seconds / 3600).toFixed(1)}h ago`;
  }
  return `${(seconds / 86400).toFixed(1)}d ago`;
}

function sumValues(obj) {
  return Object.values(obj || {}).reduce((total, value) => total + Number(value || 0), 0);
}

function renderStageBadges(values) {
  const items = Array.isArray(values) ? values : [];
  if (!items.length) {
    return '<span class="sub">idle</span>';
  }
  return `<div class="mini-badges">${items.map((item) => `<span class="mini-badge">${esc(item)}</span>`).join("")}</div>`;
}

function renderLiveOps(values, emptyLabel = "No running operations") {
  const items = Array.isArray(values) ? values : [];
  if (!items.length) {
    return `<span class="sub">${esc(emptyLabel)}</span>`;
  }
  return `<div class="live-ops">${items.map((item) => `
    <div class="live-op">
      <div class="live-op-head">
        <span>${esc(item.stage || item.component_label || item.component || "")}</span>
        <span class="${badgeClass(item.activity_state || item.status)}">${esc(titleCase(item.activity_state || item.status || ""))}</span>
      </div>
      <div class="sub">${esc(item.component_label || item.component || "")} · ${esc(item.operation || "")}</div>
      <div class="sub">${esc(formatTs(item.started_at || ""))} · ${esc(formatAgeSeconds(item.age_seconds || 0))}</div>
      ${renderProgressItems(item.progress_items)}
    </div>
  `).join("")}</div>`;
}

function renderProgressItems(values) {
  const items = Array.isArray(values) ? values : [];
  if (!items.length) {
    return "";
  }
  return `<div class="progress-items">${items.map((item) => {
    let valueText = "";
    if (item.key === "file_size_bytes" || item.key === "total_bytes") {
      valueText = formatBytes(item.value);
    } else if (item.key === "processed_bytes" && item.value && typeof item.value === "object") {
      valueText = `${formatBytes(item.value.processed)} / ${formatBytes(item.value.total)}`;
    } else {
      valueText = String(item.value ?? "");
    }
    return `<div class="progress-item"><strong>${esc(item.label || item.key || "")}</strong><span>${esc(valueText)}</span></div>`;
  }).join("")}</div>`;
}

function switchOpsTab(tab) {
  const nextTab = OPS_TABS.has(tab) ? tab : "overview";
  currentOpsTab = nextTab;
  for (const button of document.querySelectorAll("[data-tab-button]")) {
    button.classList.toggle("is-active", button.getAttribute("data-tab-button") === nextTab);
  }
  for (const panel of document.querySelectorAll("[data-tab-panel]")) {
    panel.hidden = panel.getAttribute("data-tab-panel") !== nextTab;
  }
  try {
    window.localStorage.setItem("bizrag.ops.tab", nextTab);
  } catch (_err) {
  }
}

function preferredOpsTab() {
  try {
    const stored = window.localStorage.getItem("bizrag.ops.tab");
    if (OPS_TABS.has(stored)) {
      return stored;
    }
  } catch (_err) {
  }
  return "overview";
}

function openInspectorModal(title, summaryHtml, payload) {
  document.getElementById("inspector-title").textContent = title || "Details";
  document.getElementById("inspector-summary").innerHTML = summaryHtml || "";
  document.getElementById("inspector-raw").textContent = JSON.stringify(payload || {}, null, 2);
  document.getElementById("inspector-modal").showModal();
}

function closeInspectorModal() {
  document.getElementById("inspector-modal").close();
}

function openAlertModal(index) {
  const item = currentAlerts[index];
  if (!item) return;
  const samples = Array.isArray(item.samples) ? item.samples : [];
  openInspectorModal(
    item.title || item.rule_id || "Alert",
    `
      <div class="inspector-grid">
        <div><strong>Rule</strong>${esc(item.rule_id || "")}</div>
        <div><strong>Severity</strong><span class="${badgeClass(item.severity)}">${esc(item.severity || "")}</span></div>
        <div><strong>Value</strong>${esc(formatAlertValue(item))}</div>
        <div><strong>Message</strong>${esc(item.message || "")}</div>
      </div>
      ${samples.length ? `<div class="inspector-block"><strong>Samples</strong>${samples.map((sample) => `
        <div class="inspector-item">
          <div>${esc(sample.component_label || sample.component || "")} · ${esc(sample.operation || "")}</div>
          <div class="sub">${esc(sample.kb_id || "system")} · ${esc(formatTs(sample.started_at || ""))}</div>
          <div class="sub">${esc(sample.error_message || "")}</div>
        </div>
      `).join("")}</div>` : ""}
    `,
    item,
  );
}

function openHealthModal(index) {
  const check = currentHealthChecks[index];
  if (!check) return;
  const metrics = currentOverview?.components?.[check.id] || null;
  openInspectorModal(
    check.label || check.id || "Health Check",
    `
      <div class="inspector-grid">
        <div><strong>Component</strong>${esc(check.id || "")}</div>
        <div><strong>Status</strong><span class="${badgeClass(check.status)}">${esc(titleCase(check.status || ""))}</span></div>
        <div><strong>Detail</strong>${esc(check.detail || "")}</div>
        <div><strong>Description</strong>${esc(check.description || "")}</div>
      </div>
      ${metrics ? `
        <div class="inspector-block">
          <strong>Recent Metrics</strong>
          <div class="inspector-grid">
            <div><strong>Latest Operation</strong>${esc(metrics.latest_operation || "")}</div>
            <div><strong>Active Now</strong>${esc(metrics.active_count || 0)}</div>
            <div><strong>Stalled</strong>${esc(metrics.stalled_count || 0)}</div>
            <div><strong>Status Counts</strong>${esc(JSON.stringify(metrics.status_counts || {}))}</div>
            <div><strong>P95 Latency</strong>${esc(formatDuration(metrics.latency_ms?.p95_ms || 0))}</div>
          </div>
        </div>
      ` : ""}
    `,
    { check, metrics },
  );
}

function openKbModal(index) {
  const item = currentKbActivity[index];
  if (!item) return;
  openInspectorModal(
    item.kb_id || "KB Activity",
    `
      <div class="inspector-grid">
        <div><strong>Collection</strong>${esc(item.collection_name || "")}</div>
        <div><strong>Active Stages</strong>${esc(item.active_count || 0)}</div>
        <div><strong>Stalled Stages</strong>${esc(item.stalled_count || 0)}</div>
        <div><strong>Documents</strong>${esc(JSON.stringify(item.documents_by_status || {}))}</div>
        <div><strong>KB Tasks</strong>${esc(JSON.stringify(item.task_activity || {}))}</div>
        <div><strong>RustFS Events</strong>${esc(JSON.stringify(item.event_activity || {}))}</div>
        <div><strong>Current Stages</strong>${esc((item.current_stages || []).join(", ") || "idle")}</div>
      </div>
      <div class="inspector-block">
        <strong>Active Operations</strong>
        ${renderLiveOps(item.live_operations, "No active operations for this KB")}
      </div>
      <div class="inspector-block">
        <strong>Recently Completed Stages For Active File</strong>
        ${renderLiveOps(item.recent_completed_stages, "No completed stage details captured yet")}
      </div>
      <div class="inspector-block">
        <strong>Stalled Operations</strong>
        ${renderLiveOps(item.stalled_operations, "No stalled operations for this KB")}
      </div>
      <div class="inspector-block">
        <strong>Latest Activity</strong>
        ${item.latest_activity ? `
          <div class="inspector-item">
            <div>${esc(item.latest_activity.component_label || item.latest_activity.component || "")} · ${esc(item.latest_activity.operation || "")}</div>
            <div class="sub">${esc(item.latest_activity.status || "")} · ${esc(formatTs(item.latest_activity.started_at || ""))}</div>
            <div class="sub">${esc(formatDuration(item.latest_activity.duration_ms || 0))}</div>
          </div>
        ` : '<div class="sub">No recent activity</div>'}
      </div>
      <div class="inspector-block">
        <strong>Latest Failure</strong>
        ${item.latest_failure ? `
          <div class="inspector-item">
            <div>${esc(item.latest_failure.component_label || item.latest_failure.component || "")} · ${esc(item.latest_failure.operation || "")}</div>
            <div class="sub">${esc(formatTs(item.latest_failure.started_at || ""))}</div>
            <div class="sub">${esc(item.latest_failure.error_message || "")}</div>
          </div>
        ` : '<div class="sub">No recent failure</div>'}
      </div>
    `,
    item,
  );
}

async function fetchJson(path) {
  const resp = await fetch(path, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function renderOverview(data) {
  currentOverview = data;
  document.getElementById("generated-at").textContent = `Generated at ${formatTs(data.generated_at)} · auto-refresh every 5s`;
  const healthStatus = data.health?.status || "unknown";
  const pill = document.getElementById("health-pill");
  pill.textContent = `health: ${healthStatus}`;
  pill.className = `pill ${badgeClass(healthStatus)}`;

  const inventory = data.inventory || {};
  const inventoryCards = [
    ["Knowledge Bases", inventory.kbs_total || 0],
    ["Active Documents", inventory.documents_active || 0],
    ["Queued Events", inventory.queued_events || 0],
    ["Active Operations", inventory.running_operations || 0],
    ["Stalled Operations", inventory.stalled_operations || 0],
  ];
  document.getElementById("inventory-grid").innerHTML = inventoryCards.map(([label, value]) => (
    `<div class="card"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div></div>`
  )).join("");

  const alerts = data.alerts || [];
  currentAlerts = alerts;
  document.getElementById("alerts").innerHTML = alerts.length ? alerts.map((item, index) => (
    `<button type="button" class="alert interactive-card ${esc(item.severity)}" onclick="openAlertModal(${index})">
      <div class="alert-head">
        <div>
          <div class="alert-rule">${esc(item.rule_id)}</div>
          <div class="alert-title">${esc(item.title || item.rule_id)}</div>
        </div>
        <div class="${badgeClass(item.severity)}">${esc(formatAlertValue(item))}</div>
      </div>
      <div class="alert-message">${esc(item.message || "")}</div>
      ${(item.samples || []).length ? `<div class="alert-samples">${item.samples.map((sample) => `
        <div class="alert-sample">
          <div>${esc(sample.component_label || sample.component || "")} · ${esc(sample.operation || "")}</div>
          <div>${esc(sample.kb_id || "system")} · ${esc(formatTs(sample.started_at || ""))}</div>
          <div>${esc(compact(sample.error_message || "", 160))}</div>
        </div>
      `).join("")}</div>` : ""}
    </button>`
  )).join("") : '<div class="empty">No active alerts</div>';

  const checks = data.health?.checks || [];
  currentHealthChecks = checks;
  document.getElementById("health-grid").innerHTML = checks.map((check, index) => {
    const metrics = data.components?.[check.id] || null;
    return (
      `<button type="button" class="health-item interactive-card" onclick="openHealthModal(${index})">
        <div class="health-top">
          <div>
            <div class="health-title">${esc(check.label || check.id || "")}</div>
            <div class="health-id">${esc(check.id || "")}</div>
          </div>
          <div class="status ${badgeClass(check.status)}">${esc(titleCase(check.status))}</div>
        </div>
        <div class="detail">${esc(check.detail)}</div>
        ${metrics ? `
          <div class="health-metrics">
            <div><strong>Latest</strong>${esc(metrics.latest_operation || metrics.latest_status || "")}</div>
            <div><strong>Active Now</strong>${esc(metrics.active_count || 0)}</div>
            <div><strong>Stalled</strong>${esc(metrics.stalled_count || 0)}</div>
            <div><strong>Last Result</strong>${esc(titleCase(metrics.latest_status || "idle"))}</div>
          </div>
        ` : ""}
        <div class="desc">${esc(check.description || "")}</div>
      </button>`
    );
  }).join("");

  const runningByKb = new Map();
  for (const row of (Array.isArray(data.running_operations) ? data.running_operations : [])) {
    const kbId = String(row?.kb_id || "");
    if (!kbId) continue;
    const items = runningByKb.get(kbId) || [];
    items.push(row);
    runningByKb.set(kbId, items);
  }

  const components = data.components || {};
  document.getElementById("component-metrics").innerHTML = Object.entries(components).map(([name, item]) => (
    `<tr>
      <td>${esc(item.label || name)}<div class="sub">${esc(item.description || "")}</div></td>
      <td>
        <div class="detail-stack">
          <div>${esc(titleCase(item.status || "idle"))}</div>
          <div class="sub">${esc(item.latest_operation || item.detail || "")}</div>
          <div class="sub">active=${esc(item.active_count || 0)} stalled=${esc(item.stalled_count || 0)}</div>
        </div>
      </td>
      <td>${esc(JSON.stringify(item.status_counts || {}))}</td>
      <td>${formatDuration(item.latency_ms?.p50_ms || 0)}</td>
      <td>${formatDuration(item.latency_ms?.p95_ms || 0)}</td>
      <td>${formatDuration(item.latency_ms?.max_ms || 0)}</td>
    </tr>`
  )).join("");

  const kbActivity = Array.isArray(data.kb_activity) ? data.kb_activity : [];
  currentKbActivity = kbActivity.map((item) => {
    const activeOps = Array.isArray(item.live_operations) && item.live_operations.length
      ? item.live_operations
      : (runningByKb.get(String(item.kb_id || "")) || []).slice(0, 8);
    return {
      ...item,
      live_operations: activeOps,
      recent_completed_stages: Array.isArray(item.recent_completed_stages) ? item.recent_completed_stages : [],
      stalled_operations: Array.isArray(item.stalled_operations) ? item.stalled_operations : [],
    };
  });
  document.getElementById("kb-activity").innerHTML = currentKbActivity.map((item, index) => (
    `<tr>
      <td>
        ${esc(item.kb_id)}
        <div class="sub">${esc(item.collection_name || "")}</div>
      </td>
      <td>
        <div class="detail-stack">
          <div>active=${esc(item.documents_by_status?.active || 0)}</div>
          <div class="sub">failed=${esc(item.documents_by_status?.failed || 0)}</div>
          <div class="sub">deleted=${esc(item.documents_by_status?.deleted || 0)}</div>
        </div>
      </td>
      <td>
        <div class="detail-stack">
          <div><strong>Active</strong></div>
          ${renderStageBadges(item.current_stages)}
          ${renderLiveOps(item.live_operations, "No live ops")}
          ${(item.stalled_operations || []).length ? `<div><strong>Stalled</strong></div>${renderLiveOps(item.stalled_operations, "No stalled ops")}` : ""}
        </div>
      </td>
      <td>
        <div class="detail-stack">
          <div>kb tasks active=${esc(item.task_activity?.active || 0)}</div>
          <div class="sub">kb tasks stalled=${esc(item.task_activity?.stalled || 0)}</div>
          <div class="sub">events queued=${esc(item.event_activity?.queued || 0)}</div>
          <div class="sub">events active=${esc(item.event_activity?.active || 0)}</div>
          <div class="sub">events stalled=${esc(item.event_activity?.stalled || 0)}</div>
        </div>
      </td>
      <td>${item.latest_activity ? `
        <div class="detail-stack">
          <div>${esc(item.latest_activity.component_label || item.latest_activity.component || "")} · ${esc(item.latest_activity.operation || "")}</div>
          <div class="sub">${esc(item.latest_activity.status || "")} · ${esc(formatTs(item.latest_activity.started_at || ""))}</div>
          <div class="sub">${esc(formatDuration(item.latest_activity.duration_ms || 0))}</div>
        </div>
      ` : '<span class="sub">No recent activity</span>'}</td>
      <td>${item.latest_failure ? `
        <div class="detail-stack">
          <div>${esc(item.latest_failure.component_label || item.latest_failure.component || "")}</div>
          <div class="sub">${esc(formatTs(item.latest_failure.started_at || ""))}</div>
          <div class="sub">${esc(compact(item.latest_failure.error_message || "", 120))}</div>
        </div>
      ` : '<span class="sub">No recent failure</span>'}</td>
      <td><button type="button" class="inline-open" onclick="openKbModal(${index})">Open</button></td>
    </tr>`
  )).join("") || '<tr><td colspan="7" class="empty">No KB activity found.</td></tr>';

  const spans = Array.isArray(data.recent_spans) ? data.recent_spans : [];
  const parentSpanIds = new Set(
    spans
      .map((item) => String(item?.parent_span_id || "").trim())
      .filter((value) => value)
  );
  currentRecentSpans = spans
    .filter((item) => !parentSpanIds.has(String(item?.span_id || "").trim()))
    .slice(0, 30);
  document.getElementById("recent-spans").innerHTML = currentRecentSpans.map((item, index) => (
    `<tr>
      <td>${esc(item.started_at)}</td>
      <td>${esc(item.component_label || item.component)}<div class="sub">${esc(item.component || "")}</div></td>
      <td>${esc(item.stage || "")}<div class="sub">${esc(item.operation || "")}</div></td>
      <td class="${badgeClass(item.status)}">${esc(item.status)}</td>
      <td title="${Number(item.duration_ms || 0).toFixed(1)} ms">${formatDuration(item.duration_ms || 0)}</td>
      <td>${esc(item.kb_id || "")}</td>
      <td><button type="button" class="span-open" onclick="openSpanModal(${index})">Open</button></td>
    </tr>`
  )).join("");

  rawPayloads.health = JSON.stringify(data.health || {}, null, 2);
  rawPayloads.overview = JSON.stringify(data, null, 2);
}

function renderFiles(data) {
  currentFileInventory = data || { items: [] };
  const items = data.items || [];
  const term = (document.getElementById("file-search")?.value || "").trim().toLowerCase();
  const filtered = term ? items.filter((item) => (
    [item.file_name, item.kb_id, item.source_uri, item.file_id].some((value) => String(value || "").toLowerCase().includes(term))
  )) : items;
  document.getElementById("file-service-summary").textContent =
    `generated at ${data.generated_at || ""} · files: ${filtered.length} / ${items.length} · db: ${data.database_path || ""}`;
  rawPayloads.files = JSON.stringify(data, null, 2);
  document.getElementById("file-service-list").innerHTML = filtered.length ? `
    <table class="file-table">
      <thead><tr><th>File</th><th>KB</th><th>Status</th><th>Chunks</th><th>Updated</th><th></th></tr></thead>
      <tbody>
        ${filtered.map((item, idx) => `
          <tr>
            <td>${esc(item.file_name || item.file_id)}<small>${esc(compact(item.source_uri, 88))}</small></td>
            <td>${esc(item.kb_id)}</td>
            <td>${esc(item.status)}</td>
            <td>${esc(item.chunk_count)}</td>
            <td>${esc(item.updated_at || "")}</td>
            <td><button type="button" class="file-open" onclick="openFileModal(${idx})">Open</button></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  ` : '<div class="empty">No file_service records found.</div>';
  currentFileInventory.filteredItems = filtered;
}

function renderKbOptions(items) {
  currentKbItems = Array.isArray(items) ? items : [];
  const select = document.getElementById("query-kb-id");
  if (!select) return;
  const previousValue = String(select.value || "");
  const options = currentKbItems.map((item) => {
    const kbId = String(item.kb_id || "");
    return `<option value="${esc(kbId)}">${esc(kbId)}</option>`;
  });
  select.innerHTML = options.length ? options.join("") : '<option value="">No KBs</option>';
  const candidates = [previousValue, loadPreferredQueryKb()].filter(Boolean);
  const nextValue = candidates.find((candidate) => (
    currentKbItems.some((item) => String(item.kb_id || "") === String(candidate))
  )) || String(currentKbItems[0]?.kb_id || "");
  if (nextValue) {
    select.value = nextValue;
    savePreferredQueryKb(nextValue);
  }
}

function renderRawDetails(label, payload) {
  return `
    <details class="query-raw">
      <summary>${esc(label)}</summary>
      <pre>${esc(JSON.stringify(payload, null, 2))}</pre>
    </details>
  `;
}

function renderRetrieveResult(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  if (!items.length) {
    return '<div class="query-empty">No retrieval hits returned.</div>' + renderRawDetails("Raw response", data);
  }
  return `
    <div class="query-stack">
      ${items.map((item, index) => {
        const sources = Array.isArray(item?.metadata?.retrieval_sources) ? item.metadata.retrieval_sources.join(", ") : "";
        return `
          <div class="query-hit">
            <div class="query-hit-head">
              <div class="query-hit-title">${esc(item.title || item.file_name || `Hit ${index + 1}`)}</div>
              <div class="query-hit-score">score ${Number(item.score || 0).toFixed(4)}</div>
            </div>
            <div class="query-hit-meta">
              <span>file: ${esc(item.file_name || "")}</span>
              <span>sheet: ${esc(item.sheet_name || "")}</span>
              <span>row: ${esc(item.row_index ?? "")}</span>
              <span>doc_id: ${esc(item.doc_id || "")}</span>
              <span>source: ${esc(sources || "unknown")}</span>
            </div>
            <div class="query-hit-content">${esc(item.content || "")}</div>
            ${renderRawDetails("Raw item", item)}
          </div>
        `;
      }).join("")}
    </div>
    ${renderRawDetails("Raw response", data)}
  `;
}

function renderRagResult(data) {
  const citations = Array.isArray(data?.citations) ? data.citations : [];
  return `
    <div class="query-stack">
      <div class="query-answer">${esc(data?.answer || "No answer returned.")}</div>
      ${citations.length ? citations.map((item, index) => `
        <div class="query-hit">
          <div class="query-hit-head">
            <div class="query-hit-title">${esc(item.title || item.file_name || `Citation ${index + 1}`)}</div>
            <div class="query-hit-score">score ${Number(item.score || 0).toFixed(4)}</div>
          </div>
          <div class="query-hit-meta">
            <span>file: ${esc(item.file_name || "")}</span>
            <span>sheet: ${esc(item.sheet_name || "")}</span>
            <span>row: ${esc(item.row_index ?? "")}</span>
            <span>doc_id: ${esc(item.doc_id || "")}</span>
          </div>
          <div class="query-hit-content">${esc(item.content || "")}</div>
          ${renderRawDetails("Raw citation", item)}
        </div>
      `).join("") : '<div class="query-empty">No citations returned.</div>'}
    </div>
    ${renderRawDetails("Raw response", data)}
  `;
}

function setQueryResult(title, body, meta = "") {
  document.getElementById("query-result-title").textContent = title;
  document.getElementById("query-result-meta").textContent = meta;
  document.getElementById("query-result-body").innerHTML = body;
}

async function runQuery(mode) {
  const kbId = (document.getElementById("query-kb-id")?.value || "").trim();
  const query = (document.getElementById("query-text")?.value || "").trim();
  const topK = Number(document.getElementById("query-top-k")?.value || 3);
  const systemPrompt = (document.getElementById("query-system-prompt")?.value || "").trim();
  if (!kbId) {
    setQueryResult("Missing KB", "Select a KB before sending a request.");
    return;
  }
  if (!query) {
    setQueryResult("Missing Query", "Enter a query before sending a request.");
    return;
  }
  const buttons = Array.from(document.querySelectorAll(".action-row button"));
  for (const button of buttons) button.disabled = true;
  setQueryResult(`Running ${mode}...`, "");
  try {
    const payload = {
      kb_id: kbId,
      query,
      top_k: Number.isFinite(topK) && topK > 0 ? topK : 3,
    };
    if (mode === "rag" && systemPrompt) {
      payload.system_prompt = systemPrompt;
    }
    const path = mode === "rag" ? "/api/v1/rag" : "/api/v1/retrieve";
    const startedAt = performance.now();
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const elapsedMs = performance.now() - startedAt;
    const text = await resp.text();
    let body = `<pre>${esc(text)}</pre>`;
    try {
      const data = JSON.parse(text);
      body = mode === "rag" ? renderRagResult(data) : renderRetrieveResult(data);
    } catch (_err) {
    }
    const meta = `kb_id=${kbId} · status=${resp.status} · elapsed=${elapsedMs.toFixed(1)} ms`;
    setQueryResult(`${mode.toUpperCase()} response`, body, meta);
  } catch (err) {
    setQueryResult(`${mode.toUpperCase()} failed`, String(err));
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

function openFileModal(index) {
  const item = (currentFileInventory.filteredItems || [])[index];
  if (!item) return;
  document.getElementById("file-modal-title").textContent = item.file_name || item.file_id;
  document.getElementById("file-modal-meta").innerHTML = `
    <div><strong>File ID</strong>${esc(item.file_id)}</div>
    <div><strong>KB</strong>${esc(item.kb_id)}</div>
    <div><strong>Source URI</strong>${esc(item.source_uri)}</div>
    <div><strong>Status</strong>${esc(item.status)}</div>
    <div><strong>Watch Status</strong>${esc(item.watch_status || "")}</div>
    <div><strong>Document Status</strong>${esc(item.document_status || "")}</div>
    <div><strong>Version</strong>${esc(item.current_version)}</div>
    <div><strong>Storage Key</strong>${esc(item.storage_key || "")}</div>
    <div><strong>Storage Path</strong>${esc(item.storage_path || "")}</div>
    <div><strong>Corpus Path</strong>${esc(item.corpus_path || "")}</div>
    <div><strong>Chunk File</strong>${esc(item.chunk_file || "")}</div>
  `;
  const chunks = item.chunks || [];
  document.getElementById("file-modal-chunks").innerHTML = chunks.length ? chunks.map((chunk) => `
    <div class="chunk-item">
      <div class="chunk-head"><span>chunk_id: ${esc(chunk.chunk_id)}</span><span>vector_id: ${esc(chunk.vector_id)}</span></div>
      <div class="chunk-head"><span>doc_id: ${esc(chunk.doc_id)}</span><span>row: ${esc(chunk.row_index ?? "")}</span></div>
      <div class="chunk-hover-note">Hover to preview chunk text</div>
      <div class="chunk-tooltip">${esc(chunk.snippet)}</div>
    </div>
  `).join("") : '<div class="empty">No chunks found for this file in the current KB workspace.</div>';
  document.getElementById("file-modal").showModal();
}

function closeFileModal() {
  document.getElementById("file-modal").close();
}

function openSpanModal(index) {
  const item = currentRecentSpans[index];
  if (!item) return;
  const details = item.details_json || {};
  const request = details.request || {};
  const response = details.response || {};
  const hasRequest = request && Object.keys(request).length > 0;
  const hasResponse = response && Object.keys(response).length > 0;
  document.getElementById("span-modal-title").textContent = `${item.component || "span"} · ${item.operation || ""}`;
  document.getElementById("span-modal-meta").innerHTML = `
    <div><strong>Started</strong>${esc(item.started_at || "")}</div>
    <div><strong>Status</strong>${esc(item.status || "")}</div>
    <div><strong>Duration</strong>${esc(formatDuration(item.duration_ms || 0))}</div>
    <div><strong>KB</strong>${esc(item.kb_id || "")}</div>
    <div><strong>Trace ID</strong>${esc(item.trace_id || "")}</div>
    <div><strong>Span ID</strong>${esc(item.span_id || "")}</div>
  `;
  document.getElementById("span-request-section").hidden = !hasRequest;
  document.getElementById("span-response-section").hidden = !hasResponse;
  document.getElementById("span-modal-request").textContent = hasRequest ? JSON.stringify(request, null, 2) : "";
  document.getElementById("span-modal-response").textContent = hasResponse ? JSON.stringify(response, null, 2) : "";
  document.getElementById("span-modal-details").textContent = JSON.stringify(details, null, 2) || "{}";
  document.getElementById("span-modal").showModal();
}

function closeSpanModal() {
  document.getElementById("span-modal").close();
}

function openRawModal(kind) {
  const titles = {
    health: "Raw Health",
    overview: "Raw Overview",
    metrics: "Raw Metrics",
    files: "Raw File Inventory",
  };
  document.getElementById("raw-modal-title").textContent = titles[kind] || "Raw Data";
  document.getElementById("raw-modal-content").textContent = rawPayloads[kind] || "";
  document.getElementById("raw-modal").showModal();
}

function closeRawModal() {
  document.getElementById("raw-modal").close();
}

async function refreshOverview() {
  try {
    renderOverview(await fetchJson("/api/v1/admin/ops/overview"));
  } catch (err) {
    console.error("failed to refresh ops overview", err);
  }
}

async function refreshMetrics() {
  try {
    const resp = await fetch("/api/v1/admin/ops/metrics", { cache: "no-store" });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    rawPayloads.metrics = await resp.text();
  } catch (err) {
    console.error("failed to refresh ops metrics", err);
  }
}

async function refreshFiles() {
  try {
    renderFiles(await fetchJson("/api/v1/admin/ops/files?limit=100&chunk_preview=8"));
  } catch (err) {
    console.error("failed to refresh file inventory", err);
  }
}

async function refreshKbOptions() {
  try {
    const data = await fetchJson("/api/v1/admin/kbs");
    renderKbOptions(data.items || []);
  } catch (err) {
    console.error("failed to refresh kb list", err);
  }
}

async function bootstrap() {
  switchOpsTab(preferredOpsTab());
  const kbSelect = document.getElementById("query-kb-id");
  if (kbSelect && !kbSelect.dataset.persistBound) {
    kbSelect.addEventListener("change", (event) => {
      savePreferredQueryKb(event.target?.value || "");
    });
    kbSelect.dataset.persistBound = "true";
  }
  await Promise.all([refreshOverview(), refreshMetrics(), refreshFiles(), refreshKbOptions()]);
  setInterval(() => {
    refreshOverview();
    refreshMetrics();
    refreshFiles();
    refreshKbOptions();
  }, 5000);
}

window.openFileModal = openFileModal;
window.closeFileModal = closeFileModal;
window.openSpanModal = openSpanModal;
window.closeSpanModal = closeSpanModal;
window.openRawModal = openRawModal;
window.closeRawModal = closeRawModal;
window.openAlertModal = openAlertModal;
window.openHealthModal = openHealthModal;
window.openKbModal = openKbModal;
window.closeInspectorModal = closeInspectorModal;
window.switchOpsTab = switchOpsTab;
window.runQuery = runQuery;
window.renderFiles = renderFiles;

bootstrap();

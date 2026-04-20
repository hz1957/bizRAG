const rawPayloads = {
  health: "",
  overview: "",
  metrics: "",
  files: "",
};

let currentFileInventory = { items: [] };
let currentKbItems = [];
let currentRecentSpans = [];

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function badgeClass(status) {
  return `status-${status || "idle"}`;
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

async function fetchJson(path) {
  const resp = await fetch(path, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function renderOverview(data) {
  document.getElementById("generated-at").textContent = `Generated at ${data.generated_at} · auto-refresh every 15s`;
  const healthStatus = data.health?.status || "unknown";
  const pill = document.getElementById("health-pill");
  pill.textContent = `health: ${healthStatus}`;
  pill.className = `pill ${badgeClass(healthStatus)}`;

  const inventory = data.inventory || {};
  const inventoryCards = [
    ["Knowledge Bases", inventory.kbs_total || 0],
    ["Documents", Object.values(inventory.documents_by_status || {}).reduce((a, b) => a + b, 0)],
    ["Tasks", Object.values(inventory.tasks_by_status || {}).reduce((a, b) => a + b, 0)],
    ["Queued Events", (inventory.rustfs_events_by_status || {}).queued || 0],
  ];
  document.getElementById("inventory-grid").innerHTML = inventoryCards.map(([label, value]) => (
    `<div class="card"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div></div>`
  )).join("");

  const alerts = data.alerts || [];
  document.getElementById("alerts").innerHTML = alerts.length ? alerts.map((item) => (
    `<div class="alert ${esc(item.severity)}"><strong>${esc(item.rule_id)}</strong><span>${esc(formatAlertValue(item))}</span></div>`
  )).join("") : '<div class="empty">No active alerts</div>';

  const checks = data.health?.checks || [];
  document.getElementById("health-grid").innerHTML = checks.map((check) => (
    `<div class="health-item"><div class="name">${esc(check.name)}</div><div class="status ${badgeClass(check.status)}">${esc(check.status)}</div><div class="detail">${esc(check.detail)}</div></div>`
  )).join("");

  const components = data.components || {};
  document.getElementById("component-metrics").innerHTML = Object.entries(components).map(([name, item]) => (
    `<tr><td>${esc(name)}<div class="sub">${esc(item.detail || "")}</div></td><td>${esc(JSON.stringify(item.status_counts || {}))}</td><td>${formatDuration(item.latency_ms?.p50_ms || 0)}</td><td>${formatDuration(item.latency_ms?.p95_ms || 0)}</td><td>${formatDuration(item.latency_ms?.max_ms || 0)}</td></tr>`
  )).join("");

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
    `<tr><td>${esc(item.started_at)}</td><td>${esc(item.component)}</td><td>${esc(item.operation)}</td><td class="${badgeClass(item.status)}">${esc(item.status)}</td><td title="${Number(item.duration_ms || 0).toFixed(1)} ms">${formatDuration(item.duration_ms || 0)}</td><td>${esc(item.kb_id || "")}</td><td><button type="button" class="span-open" onclick="openSpanModal(${index})">Open</button></td></tr>`
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
  const options = currentKbItems.map((item) => {
    const kbId = String(item.kb_id || "");
    return `<option value="${esc(kbId)}">${esc(kbId)}</option>`;
  });
  select.innerHTML = options.length ? options.join("") : '<option value="">No KBs</option>';
  const preferred = currentKbItems.find((item) => String(item.kb_id || "").includes("contracts_compose_auto"));
  if (preferred) {
    select.value = String(preferred.kb_id);
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
    <div><strong>Version</strong>${esc(item.current_version)}</div>
    <div><strong>Storage Key</strong>${esc(item.storage_key || "")}</div>
    <div><strong>Storage Path</strong>${esc(item.storage_path || "")}</div>
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
    renderFiles(await fetchJson("/api/v1/admin/ops/files?limit=24&chunk_preview=8"));
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
  await Promise.all([refreshOverview(), refreshMetrics(), refreshFiles(), refreshKbOptions()]);
  setInterval(() => {
    refreshOverview();
    refreshMetrics();
    refreshFiles();
    refreshKbOptions();
  }, 15000);
}

window.openFileModal = openFileModal;
window.closeFileModal = closeFileModal;
window.openSpanModal = openSpanModal;
window.closeSpanModal = closeSpanModal;
window.openRawModal = openRawModal;
window.closeRawModal = closeRawModal;
window.runQuery = runQuery;
window.renderFiles = renderFiles;

bootstrap();

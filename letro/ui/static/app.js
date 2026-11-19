"use strict";

const state = {
  episodes: [],
  summary: null,
  table: "ledger",
  cursor: 0,
  limit: 25,
  total: 0,
  running: false,
  lastFocus: null,
};

const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (value !== null && value !== undefined && value !== false) {
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
};

const decimals = { KZT: 2, USD: 2, EUR: 2, GBP: 2, JPY: 0 };

const formatMinor = (value, currency) => {
  if (value === null || value === undefined) return "—";
  const digits = decimals[currency] ?? 2;
  const major = Number(value) / 10 ** digits;
  const text = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(major);
  return `${text} ${currency || ""}`.trim();
};

const formatNumber = (value, digits = 3) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
};

const formatReward = (value) => {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(3)}`;
};

const fetchJSON = async (url, options = {}) => {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    const message = payload && payload.error ? payload.error : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
};

const register = document.getElementById("register");
const registerCount = document.getElementById("register-count");
const filter = document.getElementById("filter");
const empty = document.getElementById("empty");
const work = document.getElementById("work");
const episodeId = document.getElementById("episode-id");
const split = document.getElementById("split");
const cleanFlag = document.getElementById("clean-flag");
const episodeMeta = document.getElementById("episode-meta");
const countLedger = document.getElementById("count-ledger");
const countDocuments = document.getElementById("count-documents");
const countIssues = document.getElementById("count-issues");
const policy = document.getElementById("policy");
const runButton = document.getElementById("run");
const controlNote = document.getElementById("control-note");
const runError = document.getElementById("run-error");
const result = document.getElementById("result");
const stamp = document.getElementById("stamp");
const stampWord = document.getElementById("stamp-word");
const stampSub = document.getElementById("stamp-sub");
const scoreF1 = document.getElementById("score-f1");
const scoreP = document.getElementById("score-p");
const scoreR = document.getElementById("score-r");
const scoreReward = document.getElementById("score-reward");
const scoreSteps = document.getElementById("score-steps");
const scoreTime = document.getElementById("score-time");
const findingsNote = document.getElementById("findings-note");
const findingList = document.getElementById("finding-list");
const findingEmpty = document.getElementById("finding-empty");
const issueTypes = document.getElementById("issue-types");
const recordsHead = document.getElementById("records-head");
const recordsBody = document.getElementById("records-body");
const pagerLabel = document.getElementById("pager-label");
const prev = document.getElementById("prev");
const next = document.getElementById("next");
const drawer = document.getElementById("drawer");
const drawerTitle = document.getElementById("drawer-title");
const drawerBody = document.getElementById("drawer-body");
const drawerClose = document.getElementById("drawer-close");

const policyNotes = {
  reconciliation: "Flags every open invoice balance; legitimately open invoices become false accusations.",
  thorough: "Mirrors the reference audit and is an upper bound, not the scored baseline.",
  random_explorer: "Pages a fixed sample, then submits. A control for low-information behaviour.",
  mark_all: "Submits thirty plausible rows. The attack the terminal reward must reject.",
};

const updateControlNote = () => {
  controlNote.textContent = policyNotes[policy.value] || "";
};

const renderRegister = () => {
  const query = filter.value.trim().toLowerCase();
  const matches = state.episodes.filter((episode) => {
    if (!query) return true;
    return (
      episode.episode_id.toLowerCase().includes(query) ||
      episode.split.toLowerCase().includes(query)
    );
  });
  register.replaceChildren();
  registerCount.textContent = `${state.episodes.length} episodes`;
  if (!matches.length) {
    register.append(el("p", { class: "register-count", text: "No episode matches." }));
    return;
  }
  for (const splitName of ["train", "dev"]) {
    const group = matches.filter((episode) => episode.split === splitName);
    if (!group.length) continue;
    const block = el("div", { class: "register-group" });
    block.append(el("h3", { text: splitName }));
    for (const episode of group) {
      const selected = state.summary && state.summary.episode_id === episode.episode_id;
      const button = el(
        "button",
        {
          class: "episode-button",
          type: "button",
          "aria-current": selected ? "true" : "false",
          onclick: () => selectEpisode(episode.episode_id),
        },
        [
          el("span", { class: "id", text: episode.episode_id }),
          el("span", { class: "issues", text: `${episode.issues} issue${episode.issues === 1 ? "" : "s"}` }),
          el("span", {
            class: "sub",
            text: `${episode.clean ? "clean" : "erroneous"} · ${episode.ledger_rows} rows · seed ${episode.seed}`,
          }),
        ],
      );
      block.append(button);
    }
    register.append(block);
  }
};

const updateSummary = (summary) => {
  episodeId.textContent = summary.episode_id;
  split.textContent = summary.split;
  cleanFlag.hidden = !summary.clean;
  const manifest = summary.manifest;
  episodeMeta.textContent = `${manifest.period_start.slice(0, 10)} → ${manifest.period_end.slice(0, 10)} · ${manifest.base_currency} · ${manifest.timezone}`;
  countLedger.textContent = summary.counts.ledger;
  countDocuments.textContent = summary.counts.invoices + summary.counts.payments;
  countIssues.textContent = summary.truth.count;
  issueTypes.textContent = summary.truth.types.length ? summary.truth.types.join(" · ") : "none declared";
  findingsNote.textContent = `${summary.truth.count} declared`;
  result.hidden = true;
  runError.hidden = true;
  findingList.replaceChildren();
  findingEmpty.hidden = false;
  findingEmpty.textContent = "Run a policy to see its submitted findings.";
  stampWord.textContent = "unscored";
  stampSub.textContent = "run a policy";
  stamp.className = "stamp unscored";
};

const selectEpisode = async (id) => {
  if (state.running) return;
  runError.hidden = true;
  try {
    const summary = await fetchJSON(`/api/episodes/${encodeURIComponent(id)}/summary`);
    state.summary = summary;
    state.table = "ledger";
    state.cursor = 0;
    updateSummary(summary);
    renderRegister();
    empty.hidden = true;
    work.hidden = false;
    document.querySelectorAll(".tabs button").forEach((button) => {
      button.setAttribute("aria-selected", button.dataset.table === "ledger" ? "true" : "false");
    });
    await loadTable(0);
  } catch (error) {
    showError(error.message);
  }
};

const showError = (message) => {
  runError.textContent = message;
  runError.hidden = false;
};

const columnsFor = (table) => {
  if (table === "ledger") {
    return ["Row", "Timestamp", "Account", "Debit", "Credit", "Currency", "Entity", "Invoice", "Payment"];
  }
  if (table === "invoices") {
    return ["Document", "Invoice", "Entity", "Issued", "Due", "Currency", "Total"];
  }
  if (table === "payments") {
    return ["Document", "Payment", "Timestamp", "Currency", "Amount", "Invoice refs"];
  }
  return ["Date", "Source", "Target", "Rate"];
};

const chip = (label, table, id) => {
  if (!id) return el("span", { class: "finding-label", text: "—" });
  return el("button", {
    class: "chip",
    type: "button",
    text: label,
    title: `Open ${id}`,
    onclick: () => openRecord(table, id),
  });
};

const cell = (value, className = "") => {
  return el("td", { class: className, text: value === null || value === undefined ? "—" : String(value) });
};

const renderTable = (page) => {
  recordsHead.replaceChildren(el("tr", {}, columnsFor(state.table).map((name) => el("th", { scope: "col", text: name }))));
  recordsBody.replaceChildren();
  for (const row of page.rows) {
    const tr = el("tr");
    if (state.table === "ledger") {
      tr.append(
        el("td", { class: "mono" }, [chip(row.row_id, "ledger", row.row_id)]),
        cell(row.timestamp, "mono"),
        cell(row.account, "mono"),
        cell(formatMinor(row.debit_minor, row.currency), "num"),
        cell(formatMinor(row.credit_minor, row.currency), "num"),
        cell(row.currency, "mono"),
        cell(row.entity_id, "mono"),
        el("td", { class: "mono" }, [row.invoice_id ? chip(row.invoice_id, "invoices", row.invoice_id) : el("span", { class: "dim", text: "—" })]),
        el("td", { class: "mono" }, [row.payment_id ? chip(row.payment_id, "payments", row.payment_id) : el("span", { class: "dim", text: "—" })]),
      );
    } else if (state.table === "invoices") {
      tr.append(
        el("td", { class: "mono" }, [chip(row.doc_id, "invoices", row.doc_id)]),
        el("td", { class: "mono" }, [chip(row.invoice_id, "invoices", row.invoice_id)]),
        cell(row.entity_id, "mono"),
        cell(row.issued_at, "mono"),
        cell(row.due_at, "mono"),
        cell(row.currency, "mono"),
        cell(formatMinor(row.total_minor, row.currency), "num"),
      );
    } else if (state.table === "payments") {
      tr.append(
        el("td", { class: "mono" }, [chip(row.doc_id, "payments", row.doc_id)]),
        el("td", { class: "mono" }, [chip(row.payment_id, "payments", row.payment_id)]),
        cell(row.timestamp, "mono"),
        cell(row.currency, "mono"),
        cell(formatMinor(row.amount_minor, row.currency), "num"),
        cell((row.invoice_refs || []).join(", "), "mono"),
      );
    } else {
      tr.append(
        cell(row.date, "mono"),
        cell(row.source_currency, "mono"),
        cell(row.target_currency, "mono"),
        cell(row.rate, "num"),
      );
    }
    recordsBody.append(tr);
  }
  const start = page.total === 0 ? 0 : page.cursor + 1;
  const end = page.cursor + page.rows.length;
  pagerLabel.textContent = `${start}–${end} of ${page.total}`;
  prev.disabled = page.cursor <= 0;
  next.disabled = page.next_cursor === null || page.next_cursor === undefined;
  state.cursor = page.cursor;
  state.total = page.total;
  state.nextCursor = page.next_cursor;
};

const loadTable = async (cursor) => {
  if (!state.summary) return;
  const params = new URLSearchParams({
    table: state.table,
    cursor: String(cursor),
    limit: String(state.limit),
  });
  try {
    const page = await fetchJSON(
      `/api/episodes/${encodeURIComponent(state.summary.episode_id)}/records?${params.toString()}`,
    );
    renderTable(page);
  } catch (error) {
    showError(error.message);
  }
};

const renderFindings = (findings, declared) => {
  findingList.replaceChildren();
  findingEmpty.hidden = findings.length > 0;
  findingEmpty.textContent = "No findings were submitted. On a clean company that is the correct answer; on an erroneous one it is a miss.";
  findingsNote.textContent = `${findings.length} submitted · ${declared} declared`;
  for (const finding of findings) {
    const ids = (finding.affected_ids || []).map((id) => {
      const table = id.startsWith("LED-") ? "ledger" : id.startsWith("INV-") ? "invoices" : id.startsWith("PAY-") ? "payments" : id.startsWith("DOC-INV") ? "invoices" : id.startsWith("DOC-PAY") ? "payments" : null;
      return table ? chip(id, table, id) : el("span", { class: "finding-label", text: id });
    });
    const evidence = (finding.evidence_ids || []).map((id) => {
      const table = id.startsWith("LED-") ? "ledger" : id.startsWith("INV-") ? "invoices" : id.startsWith("PAY-") ? "payments" : id.startsWith("DOC-INV") ? "invoices" : id.startsWith("DOC-PAY") ? "payments" : null;
      return table ? chip(id, table, id) : el("span", { class: "finding-label", text: id });
    });
    const item = el("li", {}, [
      el("div", { class: "finding-content" }, [
        el("div", { class: "finding-top" }, [
          el("span", { class: "finding-type", text: finding.type }),
          el("span", { class: "finding-amount", text: formatMinor(finding.claimed_amount_minor, finding.currency) }),
        ]),
        el("div", { class: "finding-ids" }, [el("span", { class: "finding-label", text: "affected" }), ...ids]),
        el("div", { class: "finding-evidence" }, [el("span", { class: "finding-label", text: "evidence" }), ...evidence]),
        el("p", { class: "finding-text", text: finding.explanation || "No explanation supplied." }),
      ]),
    ]);
    findingList.append(item);
  }
};

const renderResult = (payload) => {
  const metrics = payload.metrics || {};
  const findings = payload.findings || [];
  const f1 = metrics.f1;
  const perfect = f1 === 1;
  result.hidden = false;
  stamp.className = perfect ? "stamp clear" : "stamp";
  stampWord.textContent = perfect ? "cleared" : "exceptions";
  stampSub.textContent = payload.truncated ? "truncated" : "terminal submission";
  scoreF1.textContent = formatNumber(f1);
  scoreP.textContent = formatNumber(metrics.precision);
  scoreR.textContent = formatNumber(metrics.recall);
  scoreReward.textContent = formatReward(metrics.reward);
  scoreSteps.textContent = payload.steps;
  scoreTime.textContent = `${payload.elapsed_ms} ms`;
  renderFindings(findings, payload.truth ? payload.truth.count : 0);
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
};

const runAudit = async () => {
  if (!state.summary || state.running) return;
  state.running = true;
  runButton.disabled = true;
  runButton.textContent = "Running…";
  runButton.setAttribute("aria-busy", "true");
  runError.hidden = true;
  try {
    const payload = await fetchJSON("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        episode_id: state.summary.episode_id,
        policy: policy.value,
      }),
    });
    renderResult(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    state.running = false;
    runButton.disabled = false;
    runButton.textContent = "Run audit";
    runButton.removeAttribute("aria-busy");
  }
};

const openRecord = async (table, id) => {
  if (!state.summary) return;
  state.lastFocus = document.activeElement;
  const params = new URLSearchParams({ table, id });
  try {
    const payload = await fetchJSON(
      `/api/episodes/${encodeURIComponent(state.summary.episode_id)}/record?${params.toString()}`,
    );
    drawerTitle.textContent = id;
    drawerBody.replaceChildren(el("pre", { text: JSON.stringify(payload.record, null, 2) }));
    drawer.hidden = false;
    drawerClose.focus();
  } catch (error) {
    showError(error.message);
  }
};

const closeDrawer = () => {
  drawer.hidden = true;
  if (state.lastFocus && typeof state.lastFocus.focus === "function") state.lastFocus.focus();
};

const loadEpisodes = async () => {
  try {
    const payload = await fetchJSON("/api/episodes");
    state.episodes = payload.episodes || [];
    renderRegister();
    if (state.episodes.length) {
      await selectEpisode(state.episodes[0].episode_id);
    } else {
      empty.querySelector(".empty-title").textContent = "No episodes are installed.";
      empty.querySelector(".empty-body").textContent = "Run python scripts/build_episodes.py to build the labelled train and dev sets.";
    }
  } catch (error) {
    register.replaceChildren(el("p", { class: "register-count", text: error.message }));
    registerCount.textContent = "unavailable";
    showError(error.message);
  }
};

policy.addEventListener("change", updateControlNote);
runButton.addEventListener("click", runAudit);
prev.addEventListener("click", () => loadTable(Math.max(0, state.cursor - state.limit)));
next.addEventListener("click", () => {
  if (state.nextCursor !== null && state.nextCursor !== undefined) loadTable(state.nextCursor);
});
filter.addEventListener("input", renderRegister);
drawerClose.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !drawer.hidden) closeDrawer();
});
document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    if (!state.summary || state.running) return;
    state.table = button.dataset.table;
    state.cursor = 0;
    document.querySelectorAll(".tabs button").forEach((other) => {
      other.setAttribute("aria-selected", other === button ? "true" : "false");
    });
    loadTable(0);
  });
});

updateControlNote();
loadEpisodes();

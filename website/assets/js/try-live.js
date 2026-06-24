(() => {
  const form = document.querySelector("[data-live-form]");
  if (!form) return;

  const intent = form.querySelector("#live-intent");
  const runButton = form.querySelector("[data-live-run]");
  const coldStatus = form.querySelector("[data-cold-status]");
  const state = document.querySelector("[data-output-state]");
  const planOutput = document.querySelector("[data-plan-output]");
  const planSummary = document.querySelector("[data-plan-summary]");
  const sqlOutput = document.querySelector("[data-sql-output]");
  const resultsOutput = document.querySelector("[data-results-output]");
  const rowCount = document.querySelector("[data-row-count]");
  const errorPanel = document.querySelector("[data-error-panel]");
  const errorOutput = document.querySelector("[data-error-output]");
  const errorCaption = document.querySelector("[data-error-caption]");
  const errorTitle = document.querySelector("[data-error-title]");
  const errorNote = document.querySelector("[data-error-note]");
  const stages = [...document.querySelectorAll("[data-stage]")];

  const MAX_ROWS = 100;
  const BEST_EFFORT_PATTERNS = new Set(["metric_by_dimension_rollup", "catalog_fallback"]);

  function setStage(name, status) {
    const stage = stages.find((item) => item.dataset.stage === name);
    if (!stage) return;
    stage.classList.toggle("is-active", status === "active");
    stage.classList.toggle("is-done", status === "done");
    stage.classList.toggle("is-error", status === "error");
  }

  function reset() {
    stages.forEach((stage) => stage.classList.remove("is-active", "is-done", "is-error"));
    errorPanel.hidden = true;
    errorNote.hidden = true;
    errorCaption.textContent = "Structured error";
    errorTitle.textContent = "Request stopped";
    coldStatus.hidden = true;
    planSummary.hidden = true;
    planSummary.textContent = "";
    state.textContent = "running";
    rowCount.textContent = "0 rows";
    resultsOutput.replaceChildren(Object.assign(document.createElement("p"), {
      className: "muted",
      textContent: "Waiting for execution.",
    }));
  }

  async function post(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false || body.status === "error") {
      const error = new Error(body.error?.message || body.errors?.[0]?.message || `HTTP ${response.status}`);
      error.payload = body;
      throw error;
    }
    return body;
  }

  function showRows(rows) {
    resultsOutput.replaceChildren();
    if (!Array.isArray(rows) || rows.length === 0) {
      resultsOutput.append(Object.assign(document.createElement("p"), {
        className: "muted",
        textContent: "The governed query returned no rows.",
      }));
      rowCount.textContent = "0 rows";
      return;
    }

    const table = document.createElement("table");
    table.className = "result-table";
    const columns = Object.keys(rows[0]);
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach((column) => {
      const cell = document.createElement("th");
      cell.textContent = column;
      headRow.append(cell);
    });
    head.append(headRow);
    table.append(head);

    const body = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => {
        const cell = document.createElement("td");
        const value = row[column];
        cell.textContent = value === null || value === undefined ? "null" : String(value);
        tr.append(cell);
      });
      body.append(tr);
    });
    table.append(body);
    resultsOutput.append(table);
    rowCount.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  }

  function labelsByType(resolved, types) {
    return (resolved || [])
      .filter((row) => types.includes(row.object_type))
      .map((row) => row.label || row.id);
  }

  function describePlan(planned, query) {
    const best = planned.best || {};
    const subjects = labelsByType(best.resolved, ["measure", "metric"]);
    const dims = labelsByType(best.resolved, ["dimension"]);
    const parts = [];
    parts.push(`Interpreted as: ${subjects.join(" and ") || "(unnamed objects)"}`);
    if (dims.length) parts.push(`by ${dims.join(", ")}`);
    const grain = query.time && query.time.grain;
    if (grain) parts.push(`at ${grain} grain`);
    let suffix = "";
    if (BEST_EFFORT_PATTERNS.has(best.pattern)) suffix = " — best-effort match";
    if (planned.status === "low_confidence") suffix += " — low confidence";
    return parts.join(" ") + suffix + ".";
  }

  function renderRefusal(planned) {
    const why = planned.why || {};
    setStage("plan", "done");
    state.textContent = planned.status || "declined";
    planOutput.textContent =
      "No Query IR was produced — the planner declined rather than guessing.";
    errorCaption.textContent = "Governed refusal";
    errorTitle.textContent = "The planner declined this question";
    const note = why.rationale || why.reason || why.message || "";
    const hint = why.recovery_hint || "";
    errorNote.textContent = [note, hint]
      .filter(Boolean)
      .map((part) => (/[.!?]$/.test(part.trim()) ? part.trim() : `${part.trim()}.`))
      .join(" ");
    errorNote.hidden = !errorNote.textContent;
    errorOutput.textContent = JSON.stringify(
      { status: planned.status, why: planned.why, recovery_hints: planned.recovery_hints },
      null,
      2,
    );
    errorPanel.hidden = false;
  }

  form.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      intent.value = button.dataset.preset;
      form.querySelectorAll("[data-preset]").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = intent.value.trim();
    if (!question) {
      intent.focus();
      return;
    }

    reset();
    runButton.disabled = true;
    runButton.textContent = "Running…";
    planOutput.textContent = "Resolving governed objects and query shape…";
    sqlOutput.textContent = "Waiting for a validated plan…";
    const coldTimer = window.setTimeout(() => {
      coldStatus.hidden = false;
    }, 1500);
    let activeStage = "plan";

    try {
      setStage("plan", "active");
      const planned = await post("/api/v1/plan", { intent: question, detail: "best", limit: 1 });
      const query = planned.best?.query_ir;
      if (!query) {
        // Scope/relevance gates return ok=true with best=null: a governed
        // refusal is a designed outcome, not a transport failure.
        renderRefusal(planned);
        return;
      }
      if (!query.limit) query.limit = MAX_ROWS;
      planSummary.textContent = describePlan(planned, query);
      planSummary.hidden = false;
      planOutput.textContent = JSON.stringify({
        pattern: planned.best.pattern,
        resolved: planned.best.resolved,
        query_ir: query,
      }, null, 2);
      setStage("plan", "done");

      activeStage = "validate";
      setStage("validate", "active");
      const validated = await post("/api/v1/validate", { query, verbosity: "minimal" });
      if (validated.valid === false) throw new Error("Validation rejected the planned query.");
      setStage("validate", "done");

      activeStage = "compile";
      setStage("compile", "active");
      const compiled = await post("/api/v1/compile", {
        query,
        verbosity: "compact",
        sql_profile: "audit",
      });
      sqlOutput.textContent = compiled.rendered_sql || compiled.sql || "Compilation succeeded without rendered SQL.";
      setStage("compile", "done");

      activeStage = "execute";
      setStage("execute", "active");
      const executed = await post("/api/v1/query", {
        query,
        verbosity: "compact",
        sql_profile: "audit",
      });
      showRows(executed.rows || []);
      if (executed.rendered_sql) sqlOutput.textContent = executed.rendered_sql;
      setStage("execute", "done");
      state.textContent = "complete";
    } catch (error) {
      setStage(activeStage, "error");
      state.textContent = "stopped";
      errorPanel.hidden = false;
      errorOutput.textContent = JSON.stringify(error.payload || { message: error.message }, null, 2);
    } finally {
      window.clearTimeout(coldTimer);
      coldStatus.hidden = true;
      runButton.disabled = false;
      runButton.textContent = "Run governed query";
    }
  });
})();

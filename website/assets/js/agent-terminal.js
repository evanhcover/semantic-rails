/* agent-terminal.js - animates a fake-but-faithful agent loop on the homepage.
   The script walks a sequence of MCP-style tool calls, types each line with
   small jitter, and updates a stage indicator at the bottom. */

(function () {
  const root = document.querySelector('[data-agent-terminal]');
  if (!root) return;

  const body = root.querySelector('[data-agent-body]');
  const stageEls = Array.from(root.querySelectorAll('[data-stage]'));
  const replayBtn = root.querySelector('[data-agent-replay]');
  const skipBtn = root.querySelector('[data-agent-skip]');

  // Each entry: { kind, text?, html?, stage?, delay? }
  // kind: 'prompt' | 'user' | 'step' | 'tool' | 'block' | 'result' | 'comment' | 'blank'
  const script = [
    { kind: 'comment', text: '# Agent: "What was revenue by store last month?"' },
    { kind: 'blank' },
    { kind: 'prompt', html: '<span class="agent-user">what was revenue by store last month?</span>' },
    { kind: 'blank' },

    { kind: 'step', stage: 'discover', text: 'discover' },
    { kind: 'tool', html: '→ <span class="agent-tool">discover</span>(<span class="agent-arg">terms</span>=<span class="agent-string">"revenue", "store", "last month"</span>)' },
    { kind: 'block', html:
      'metric:        <span class="agent-value">revenue_usd</span>          <span class="agent-comment">// matched "revenue" (label, synonyms)</span>\n' +
      'dimension:     <span class="agent-value">jaffle_store.store_name</span>\n' +
      'time_role:     <span class="agent-value">order_placed_at</span>      <span class="agent-comment">// default order clock</span>\n' +
      'time_window:   <span class="agent-value">last_full_calendar_month</span>'
    },

    { kind: 'step', stage: 'inspect', text: 'inspect' },
    { kind: 'tool', html: '→ <span class="agent-tool">inspect</span>(<span class="agent-arg">object_id</span>=<span class="agent-string">"metric.revenue_usd"</span>)' },
    { kind: 'block', html:
      'definition:    <span class="agent-value">sum(order_total_cents) / 100</span>\n' +
      'unit:          <span class="agent-value">USD</span>\n' +
      'fanout_safe:   <span class="agent-success">true</span> <span class="agent-comment">// via orders → store (N:1)</span>\n' +
      'owners:        <span class="agent-value">finance, growth</span>'
    },

    { kind: 'step', stage: 'build-options', text: 'build-options' },
    { kind: 'tool', html: '→ <span class="agent-tool">build-options</span>(<span class="agent-arg">working_query</span>=<span class="agent-string">{ measure: revenue_usd, ... }</span>)' },
    { kind: 'block', html:
      'recommended:\n' +
      '  • group_by:    <span class="agent-value">jaffle_store.store_name</span>\n' +
      '  • time:        <span class="agent-value">2026-04-01 → 2026-04-30</span>\n' +
      'available:     order: revenue desc | limit 5 | 10\n' +
      'blocked:       group_by region <span class="agent-warn">// missing entity link</span>'
    },

    { kind: 'step', stage: 'validate', text: 'validate' },
    { kind: 'tool', html: '→ <span class="agent-tool">validate</span>(query_ir)' },
    { kind: 'block', html:
      'status:        <span class="agent-success">ok</span>\n' +
      'paths:         <span class="agent-value">1 of 4 candidate joins selected</span> <span class="agent-comment">// orders_store (N:1, safe)</span>\n' +
      'predicates:    <span class="agent-success">applied at correct grain</span>'
    },

    { kind: 'step', stage: 'compile', text: 'compile' },
    { kind: 'tool', html: '→ <span class="agent-tool">compile</span>(query_ir)' },
    { kind: 'block', html:
      '<span class="agent-comment">-- chosen_path: relationship.orders_store (N:1, safe)</span>\n' +
      '<span class="agent-comment">-- 1 of 4 candidate paths; deterministic, fanout-safe</span>\n' +
      '<span class="agent-tool">WITH</span> leaf_1 <span class="agent-tool">AS</span> (\n' +
      '  <span class="agent-tool">SELECT</span> store.store_name <span class="agent-tool">AS</span> g1,\n' +
      '         <span class="agent-tool">SUM</span>(o.order_total_cents / 100.0) <span class="agent-tool">AS</span> m1\n' +
      '  <span class="agent-tool">FROM</span> jaffle_order o\n' +
      '  <span class="agent-tool">JOIN</span> jaffle_store store <span class="agent-tool">ON</span> o.store_id = store.store_id\n' +
      '  <span class="agent-tool">WHERE</span> o.order_placed_at <span class="agent-tool">BETWEEN</span> <span class="agent-string">\'2026-04-01\'</span> <span class="agent-tool">AND</span> <span class="agent-string">\'2026-04-30\'</span>\n' +
      '  <span class="agent-tool">GROUP BY</span> store.store_name\n' +
      ') <span class="agent-tool">SELECT</span> g1 <span class="agent-tool">AS</span> store, m1 <span class="agent-tool">AS</span> revenue_usd <span class="agent-tool">FROM</span> leaf_1 <span class="agent-tool">ORDER BY</span> revenue_usd <span class="agent-tool">DESC</span>;'
    },

    { kind: 'step', stage: 'execute', text: 'execute' },
    { kind: 'tool', html: '→ <span class="agent-tool">execute</span>(compiled_sql, <span class="agent-arg">limit</span>=<span class="agent-value">5</span>)' },
    { kind: 'result', html:
      '<table>' +
      '<thead><tr><th>store</th><th>revenue_usd</th></tr></thead>' +
      '<tbody>' +
      '<tr><td>Brooklyn - Park Slope</td><td>$84,210.50</td></tr>' +
      '<tr><td>Manhattan - Tribeca</td><td>$71,605.00</td></tr>' +
      '<tr><td>Queens - Astoria</td><td>$52,938.25</td></tr>' +
      '<tr><td>Brooklyn - Williamsburg</td><td>$49,170.75</td></tr>' +
      '<tr><td>Manhattan - UWS</td><td>$41,002.10</td></tr>' +
      '</tbody></table>'
    },
    { kind: 'blank' },
    { kind: 'comment', text: '# 13 tools, 1 deterministic loop. No model-guessed SQL.' },
  ];

  let timers = [];
  let running = false;

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function makeLine(kind) {
    const el = document.createElement('div');
    el.className = 'agent-line';
    if (kind === 'prompt') el.classList.add('agent-prompt');
    if (kind === 'comment') el.classList.add('agent-comment');
    return el;
  }

  function setStage(stage) {
    stageEls.forEach((el) => {
      const s = el.dataset.stage;
      el.classList.remove('is-active');
      if (s === stage) {
        el.classList.add('is-active');
      } else if (passedStage(s, stage)) {
        el.classList.add('is-done');
      } else {
        el.classList.remove('is-done');
      }
    });
  }

  const order = ['discover','inspect','build-options','validate','compile','execute'];
  function passedStage(s, current) {
    return order.indexOf(s) < order.indexOf(current);
  }

  function render(immediate) {
    clearTimers();
    body.innerHTML = '';
    stageEls.forEach((el) => el.classList.remove('is-active','is-done'));
    running = true;

    let delay = 0;
    script.forEach((entry, idx) => {
      const stepDelay = immediate ? 0 : computeDelay(entry);
      delay += stepDelay;

      const t = setTimeout(() => {
        if (entry.kind === 'blank') {
          const el = document.createElement('div');
          el.className = 'agent-line';
          el.innerHTML = '&nbsp;';
          body.appendChild(el);
        } else if (entry.kind === 'step') {
          const el = document.createElement('div');
          el.innerHTML = '<span class="agent-step is-' + (entry.stage === 'build-options' ? 'build' : entry.stage) + '">' + entry.text + '</span>';
          body.appendChild(el);
          setStage(entry.stage);
        } else if (entry.kind === 'block') {
          const el = document.createElement('pre');
          el.className = 'agent-line agent-block';
          el.innerHTML = entry.html;
          body.appendChild(el);
        } else if (entry.kind === 'result') {
          const el = document.createElement('div');
          el.className = 'agent-line agent-result';
          el.innerHTML = entry.html;
          body.appendChild(el);
        } else {
          const el = makeLine(entry.kind);
          if (entry.html) el.innerHTML = entry.html;
          else if (entry.text) el.textContent = entry.text;
          body.appendChild(el);
        }
        body.scrollTop = body.scrollHeight;
        if (idx === script.length - 1) {
          running = false;
          // mark all stages done
          stageEls.forEach((el) => {
            el.classList.remove('is-active');
            el.classList.add('is-done');
          });
        }
      }, delay);
      timers.push(t);
    });
  }

  function computeDelay(entry) {
    switch (entry.kind) {
      case 'blank': return 240;
      case 'prompt': return 1300;
      case 'comment': return 700;
      case 'step': return 1050;
      case 'tool': return 750;
      case 'block': return 1100;
      case 'result': return 1300;
      default: return 500;
    }
  }

  if (replayBtn) {
    replayBtn.addEventListener('click', () => render(false));
  }
  if (skipBtn) {
    skipBtn.addEventListener('click', () => render(true));
  }

  // Respect prefers-reduced-motion: render the full output immediately, no drip.
  const reduceMotion =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Auto-start when in view (or immediately if reduced motion or no IO support)
  if (reduceMotion) {
    render(true);
  } else if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !running && body.childElementCount === 0) {
          render(false);
          io.disconnect();
        }
      });
    }, { threshold: 0.2 });
    io.observe(root);
  } else {
    render(false);
  }
})();

(function () {
  const nav = document.querySelector('[data-site-nav]');
  const toggle = document.querySelector('[data-nav-toggle]');

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      nav.classList.toggle('open');
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
    });

    nav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        nav.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  const revealNodes = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && revealNodes.length > 0) {
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('in');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0, rootMargin: '0px 0px -20px 0px' }
    );

    revealNodes.forEach(function (node, index) {
      node.style.transitionDelay = String(index * 45) + 'ms';
      observer.observe(node);
    });
  } else {
    revealNodes.forEach(function (node) {
      node.classList.add('in');
    });
  }

  const faqButtons = document.querySelectorAll('[data-faq-toggle]');
  faqButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      const card = button.closest('.faq-item');
      if (!card) {
        return;
      }

      const isOpen = card.classList.contains('open');
      card.classList.toggle('open', !isOpen);
      button.setAttribute('aria-expanded', String(!isOpen));
    });
  });

  const tabButtons = document.querySelectorAll('[data-tab-target]');
  if (tabButtons.length > 0) {
    tabButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        const scope = button.closest('[data-tab-scope]');
        if (!scope) {
          return;
        }

        scope
          .querySelectorAll('[data-tab-target]')
          .forEach(function (node) {
            node.classList.remove('active');
          });
        button.classList.add('active');

        const id = button.getAttribute('data-tab-target');
        scope
          .querySelectorAll('[data-tab-panel]')
          .forEach(function (panel) {
            panel.classList.remove('active');
          });

        const active = scope.querySelector('[data-tab-panel="' + id + '"]');
        if (active) {
          active.classList.add('active');
        }
      });
    });
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_error) {
      const field = document.createElement('textarea');
      field.value = text;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.opacity = '0';
      document.body.appendChild(field);
      field.select();
      const copied = document.execCommand('copy');
      field.remove();
      return copied;
    }
  }

  window.semanticRailsCopyText = copyText;

  const copyButtons = document.querySelectorAll('.copy-btn');
  copyButtons.forEach(function (button) {
    button.addEventListener('click', async function () {
      const pre = button.closest('.code-block')?.querySelector('pre');
      if (!pre) {
        return;
      }

      const text = pre.innerText;
      try {
        const copied = await copyText(text);
        if (!copied) {
          throw new Error('Copy command was rejected.');
        }
        const prior = button.innerText;
        button.innerText = 'Copied';
        setTimeout(function () {
          button.innerText = prior;
        }, 1200);
      } catch (_error) {
        button.innerText = 'Failed';
      }
    });
  });

  const currentPath = window.location.pathname.replace(/\/$/, '');
  document.querySelectorAll('[data-nav-link]').forEach(function (link) {
    const href = link.getAttribute('href');
    if (!href) {
      return;
    }

    const normalized = href.replace(/\/$/, '');
    if (
      currentPath === normalized ||
      (normalized !== '' && currentPath.endsWith(normalized))
    ) {
      link.classList.add('active');
    }
  });

  // Schematic rail - click/keyboard a station to reveal its explainer panel.
  const railStations = {
    capabilities: {
      step: '01 · ORIENT',
      transport: 'MCP tool',
      summary:
        'Cheap cold-start orientation. Returns the supported/unsupported capability surface (rolling windows, prior-period offsets, metric predicates, conversion, distribution) and the supported select-expression shapes so agents do not have to discover by validator rejection.',
      returns: 'capabilities[], unsupported_capabilities[], expression_shapes[]',
      fails: 'package_not_loaded',
    },
    catalog: {
      step: '02 · DISCOVER',
      transport: 'MCP tool',
      summary:
        'Enumerates entities, models, metrics, dimensions, and segments available in the package. The starting point when an agent does not know what surfaces exist yet.',
      returns: 'catalog snapshot with verbosity controls (summary / compact / full)',
      fails: 'package_not_loaded',
    },
    inspect: {
      step: '03 · DISCOVER',
      transport: 'MCP tool',
      summary:
        'Full schema, join paths, and value domain for one named object - the lookup an agent needs before it commits to a query patch.',
      returns: 'object spec, allowed dimensions/metrics, valid values, join graph',
      fails: 'unknown_object with closest_matches',
    },
    'build-options': {
      step: '04 · BUILD',
      transport: 'MCP tool',
      summary:
        'Given a partial Query IR and a builder step, returns recommended, available, and blocked legal edits. Use plan for natural-language draft generation.',
      returns: 'recommended[], available[], blocked[] with query_patch hints',
      fails: 'invalid_query with recovery_hints',
    },
    validate: {
      step: '05 · GATE',
      transport: 'MCP tool',
      summary:
        'Typed envelope that checks unknown refs, dimension mismatches, filter validity, and policy violations. Errors include recovery_hints and closest_matches - usable directly by the next tool call.',
      returns: 'normalized query AST, warnings, policy decisions',
      fails: 'unknown_dimension, dimension_mismatch, filter_invalid, policy_violation',
    },
    compile: {
      step: '06 · EMIT',
      transport: 'MCP tool',
      summary:
        'Renders deterministic warehouse SQL from a validated query. Identical input always yields byte-identical output. The response carries an explain payload - alias map, join path, rewrite trace, SQL AST - inline.',
      returns: 'rendered SQL, dialect, binding parameters, compile cache hit, explain payload',
      fails: 'compile_error (only when an upstream validate step was skipped)',
    },
    execute: {
      step: '07 · RUN',
      transport: 'MCP tool',
      summary:
        'Terminus. Runs the compiled SQL against the configured warehouse (DuckDB locally; Snowflake via Snow CLI or native connector) and returns rows.',
      returns: 'rows, column types, row_count, elapsed_ms',
      fails: 'warehouse_error (connection, permissions, runtime)',
    },
  };

  const explainer = document.querySelector('[data-rail-explainer]');
  const railSvg = document.querySelector('[data-rail-svg]');
  if (explainer && railSvg) {
    const stepEl = explainer.querySelector('[data-rail-step]');
    const nameEl = explainer.querySelector('[data-rail-name]');
    const transportEl = explainer.querySelector('[data-rail-transport]');
    const summaryEl = explainer.querySelector('[data-rail-summary]');
    const returnsEl = explainer.querySelector('[data-rail-returns]');
    const failsEl = explainer.querySelector('[data-rail-fails]');
    const closeBtn = explainer.querySelector('[data-rail-close]');
    const stations = Array.from(railSvg.querySelectorAll('.rail-station'));

    function activate(stationEl) {
      const id = stationEl.getAttribute('data-station');
      const info = railStations[id];
      if (!info) {
        return;
      }
      stations.forEach(function (s) {
        s.classList.toggle('is-active', s === stationEl);
      });
      stepEl.textContent = info.step;
      nameEl.textContent = id;
      transportEl.textContent = info.transport;
      summaryEl.textContent = info.summary;
      returnsEl.textContent = info.returns;
      failsEl.textContent = info.fails;
      explainer.hidden = false;
    }

    function clear() {
      stations.forEach(function (s) {
        s.classList.remove('is-active');
      });
      explainer.hidden = true;
    }

    stations.forEach(function (station) {
      station.addEventListener('click', function () {
        activate(station);
      });
      station.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate(station);
        }
      });
    });

    if (closeBtn) {
      closeBtn.addEventListener('click', clear);
    }
  }
})();

// Dev-console easter egg: if you're reading this, you inspect before you
// execute - which is the whole philosophy of the product.
(function () {
  try {
    console.log(
      '%cYou inspected before you executed. Good agent. \u{1F6E4}\u{FE0F}',
      'font-weight:600;font-size:13px;'
    );
    console.log(
      '%cSemantic Rails is built by Will Tremml - curious who lays the rails? ' +
        'https://github.com/wtremml18',
      'font-size:12px;'
    );
  } catch (_) {
    /* consoles are optional; rails are not */
  }
})();

/* Scroll-triggered figure animations: entity hop trace (homepage),
   annotated compile output (homepage), scoreboard race (comparisons).
   Markup ships in its finished state; this file rewinds and replays it.
   With reduced motion or without IntersectionObserver nothing runs. */
(function () {
  'use strict';

  var REDUCED =
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function onceVisible(el, fn) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            io.disconnect();
            fn();
          }
        });
      },
      { threshold: 0.3 }
    );
    io.observe(el);
  }

  function supported() {
    return !REDUCED && 'IntersectionObserver' in window;
  }

  /* ============================================================
     Entity hop trace (index.html #hoptrace)
     Three intents from the live runtime: two compile, one is
     refused with MIXED_GRAIN_INVALID. Ends resting on intent A.
     ============================================================ */
  (function () {
    var root = document.getElementById('hoptrace');
    if (!root || !supported()) return;

    var $ = function (id) { return document.getElementById(id); };
    var SPEED = 0.9; /* multiplier on every timeline step */
    var timers = [];
    function at(ms, fn) { timers.push(setTimeout(fn, ms * SPEED)); }
    function clearTimers() { timers.forEach(clearTimeout); timers = []; }

    var OVERLAYS = ['ht-hop1', 'ht-hop2a', 'ht-hop2b', 'ht-rc1', 'ht-rc2', 'ht-rc3'];
    var NODES = ['ht-n-item', 'ht-n-order', 'ht-n-customer', 'ht-n-store', 'ht-n-product'];
    var STAMPS = ['ht-stamp1', 'ht-stamp2a', 'ht-stamp2b', 'ht-stampc1', 'ht-stampc2', 'ht-stampc3'];
    var PANELS = ['ht-prof-a', 'ht-prof-b', 'ht-prof-c'];

    /* hide an overlay and arm it for a draw transition */
    function rewind(id) {
      var p = $(id);
      var len = p.getTotalLength();
      p.classList.remove('on', 'dim');
      p.style.transition = 'none';
      p.style.strokeDasharray = len;
      p.style.strokeDashoffset = len;
      void p.getBoundingClientRect();
      p.style.transition = '';
    }
    /* show an overlay fully drawn with no transition */
    function settle(id) {
      var p = $(id);
      p.style.transition = 'none';
      p.classList.add('on');
      p.style.strokeDashoffset = 0;
      void p.getBoundingClientRect();
      p.style.transition = '';
    }
    function draw(edge, zip, motion) {
      var p = $(edge);
      p.classList.add('on');
      p.style.strokeDashoffset = 0;
      if (zip) {
        $(zip).classList.add('go');
        $(motion).beginElement();
        timers.push(setTimeout(function () { $(zip).classList.remove('go'); }, 690));
      }
    }
    function setIntent(which) {
      ['a', 'b', 'c'].forEach(function (k) {
        $('ht-intent-' + k).style.display = k === which ? '' : 'none';
      });
    }
    function showPanel(id) {
      var panel = $(id);
      panel.classList.add('is-on');
      var lines = panel.querySelectorAll('.ht-ln');
      Array.prototype.forEach.call(lines, function (ln, i) {
        at(i * 320, function () { ln.classList.add('show'); });
      });
    }
    function hidePanel(id) {
      var panel = $(id);
      Array.prototype.forEach.call(panel.querySelectorAll('.ht-ln'), function (ln) {
        ln.classList.remove('show');
      });
      timers.push(setTimeout(function () { panel.classList.remove('is-on'); }, 400));
    }
    function clearAll() {
      clearTimers();
      $('ht-intent').classList.remove('show');
      setIntent('a');
      $('ht-profile').classList.remove('err');
      NODES.forEach(function (n) { $(n).classList.remove('root', 'lit', 'target', 'refused'); });
      STAMPS.forEach(function (s) { $(s).classList.remove('show'); });
      OVERLAYS.forEach(rewind);
      PANELS.forEach(function (id) {
        var panel = $(id);
        panel.classList.remove('is-on');
        Array.prototype.forEach.call(panel.querySelectorAll('.ht-ln'), function (ln) {
          ln.classList.remove('show');
        });
      });
    }
    /* the resting state: intent A complete, matching the no-JS markup */
    function restingState() {
      clearAll();
      $('ht-intent').classList.add('show');
      settle('ht-hop1');
      settle('ht-hop2a');
      $('ht-n-item').classList.add('root');
      $('ht-n-order').classList.add('lit');
      $('ht-n-customer').classList.add('lit', 'target');
      $('ht-stamp1').classList.add('show');
      $('ht-stamp2a').classList.add('show');
      var panel = $('ht-prof-a');
      panel.classList.add('is-on');
      Array.prototype.forEach.call(panel.querySelectorAll('.ht-ln'), function (ln) {
        ln.classList.add('show');
      });
    }
    function play() {
      clearAll();
      /* A: item revenue by customer type, 2 safe hops */
      at(300, function () { $('ht-intent').classList.add('show'); });
      at(1000, function () { $('ht-n-item').classList.add('root'); });
      at(1700, function () { draw('ht-hop1', 'ht-zip1', 'ht-am1'); $('ht-n-order').classList.add('lit'); });
      at(2500, function () { $('ht-stamp1').classList.add('show'); });
      at(3100, function () { draw('ht-hop2a', 'ht-zip2a', 'ht-am2a'); $('ht-n-customer').classList.add('lit'); });
      at(3900, function () { $('ht-stamp2a').classList.add('show'); });
      at(4400, function () { $('ht-n-customer').classList.add('target'); });
      at(4900, function () { showPanel('ht-prof-a'); });

      /* B: item revenue by store, replanned */
      at(8800, function () {
        ['ht-hop1', 'ht-hop2a'].forEach(function (id) { $(id).classList.remove('on'); });
        ['ht-stamp1', 'ht-stamp2a'].forEach(function (s) { $(s).classList.remove('show'); });
        $('ht-n-customer').classList.remove('target', 'lit');
        $('ht-n-order').classList.remove('lit');
        hidePanel('ht-prof-a');
        setIntent('b');
      });
      at(9300, function () { rewind('ht-hop1'); rewind('ht-hop2a'); });
      at(9600, function () { draw('ht-hop1', 'ht-zip1', 'ht-am1'); $('ht-n-order').classList.add('lit'); });
      at(10400, function () { $('ht-stamp1').classList.add('show'); });
      at(11000, function () { draw('ht-hop2b', 'ht-zip2b', 'ht-am2b'); $('ht-n-store').classList.add('lit'); });
      at(11800, function () { $('ht-stamp2b').classList.add('show'); });
      at(12300, function () { $('ht-n-store').classList.add('target'); });
      at(12800, function () { showPanel('ht-prof-b'); });

      /* C: lifetime spend by product type, refused */
      at(16600, function () {
        ['ht-hop1', 'ht-hop2b'].forEach(function (id) { $(id).classList.remove('on'); });
        ['ht-stamp1', 'ht-stamp2b'].forEach(function (s) { $(s).classList.remove('show'); });
        $('ht-n-store').classList.remove('target', 'lit');
        $('ht-n-order').classList.remove('lit');
        $('ht-n-item').classList.remove('root');
        hidePanel('ht-prof-b');
        setIntent('c');
      });
      at(17400, function () { $('ht-n-customer').classList.add('root'); });
      at(18200, function () { draw('ht-rc1'); $('ht-n-order').classList.add('lit'); });
      at(19000, function () { $('ht-stampc1').classList.add('show'); });
      at(19600, function () { draw('ht-rc2'); $('ht-n-item').classList.add('lit'); });
      at(20300, function () { $('ht-stampc2').classList.add('show'); });
      at(20900, function () { draw('ht-rc3'); $('ht-n-product').classList.add('lit'); });
      at(21900, function () {
        ['ht-rc1', 'ht-rc2', 'ht-rc3'].forEach(function (id) { $(id).classList.add('dim'); });
        $('ht-n-product').classList.add('refused');
        $('ht-stampc3').classList.add('show');
        $('ht-profile').classList.add('err');
      });
      at(22400, function () { showPanel('ht-prof-c'); });

      /* settle back on intent A */
      at(28400, restingState);
    }

    var replay = $('ht-replay');
    if (replay) {
      replay.hidden = false;
      replay.addEventListener('click', play);
    }
    clearAll();
    onceVisible(root, play);
  })();

  /* ============================================================
     Annotated compile output (index.html #xsql)
     Types the verbatim rendered_sql and pins each annotation as
     its clause lands. Progress is wall-clock based so throttled
     timers fast-forward instead of stalling.
     ============================================================ */
  (function () {
    var root = document.getElementById('xsql');
    if (!root || !supported()) return;

    var rows = Array.prototype.map.call(
      root.querySelectorAll('.xsql-row'),
      function (row) {
        var code = row.querySelector('.xsql-code');
        var probe = document.createElement('div');
        probe.innerHTML = code.innerHTML;
        return {
          row: row,
          code: code,
          html: code.innerHTML,
          text: probe.textContent,
          tagged: row.classList.contains('annotated')
        };
      }
    );
    var foot = root.querySelector('.xsql-foot');
    var timers = [];
    function at(ms, fn) { timers.push(setTimeout(fn, ms)); }
    function clearTimers() {
      timers.forEach(function (t) { clearTimeout(t); clearInterval(t); });
      timers = [];
    }
    function typeRow(item, dur) {
      var n = item.text.length;
      var t0 = performance.now();
      var iv = setInterval(function () {
        var k = Math.floor(((performance.now() - t0) / dur) * n);
        if (k >= n) {
          item.code.innerHTML = item.html;
          clearInterval(iv);
          return;
        }
        item.code.textContent = item.text.slice(0, k);
        item.code.innerHTML += '<span class="xsql-caret"></span>';
      }, 24);
      timers.push(iv);
    }
    function restingState() {
      clearTimers();
      rows.forEach(function (item) {
        item.code.innerHTML = item.html;
        if (item.tagged) item.row.classList.add('annotated');
      });
      foot.classList.add('show');
    }
    function clearAll() {
      clearTimers();
      rows.forEach(function (item) {
        item.code.innerHTML = '';
        item.row.classList.remove('annotated');
      });
      foot.classList.remove('show');
    }
    function play() {
      clearAll();
      var t = 600;
      rows.forEach(function (item) {
        var dur = 260 + item.text.length * 14;
        at(t, function () { typeRow(item, dur); });
        if (item.tagged) {
          at(t + dur + 160, function () { item.row.classList.add('annotated'); });
        }
        t += dur + (item.tagged ? 560 : 200);
      });
      at(t + 400, function () { foot.classList.add('show'); });
    }

    var replay = document.getElementById('xsql-replay');
    if (replay) {
      replay.hidden = false;
      replay.addEventListener('click', play);
    }
    clearAll();
    onceVisible(root, play);
  })();

  /* ============================================================
     Scoreboard race (comparisons.html .scoreboard)
     Animates the existing rows in place: segments grow from zero
     and the native tally counts up. Runs once.
     ============================================================ */
  (function () {
    var board = document.querySelector('.scoreboard');
    if (!board || !supported()) return;

    var rows = Array.prototype.map.call(
      board.querySelectorAll('.scoreboard-row'),
      function (row) {
        var segs = Array.prototype.map.call(
          row.querySelectorAll('.sb-seg'),
          function (seg) {
            return { el: seg, grow: parseFloat(seg.style.flex) || 1 };
          }
        );
        var strong = row.querySelector('.sb-tally strong');
        var target = strong ? parseInt(strong.textContent, 10) || 0 : 0;
        var suffix = strong ? strong.textContent.replace(/^\s*\d+/, '') : '';
        return { row: row, segs: segs, strong: strong, target: target, suffix: suffix };
      }
    );
    function countUp(item, dur) {
      var t0 = performance.now();
      function step(now) {
        var p = Math.min(1, (now - t0) / dur);
        var eased = 1 - Math.pow(1 - p, 3);
        item.strong.textContent = Math.round(item.target * eased) + item.suffix;
        if (p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }
    function arm() {
      board.classList.add('sb-anim');
      rows.forEach(function (item) {
        item.segs.forEach(function (s) { s.el.style.flexGrow = '0.001'; });
        if (item.strong) item.strong.textContent = '0' + item.suffix;
      });
      void board.getBoundingClientRect();
    }
    function play() {
      rows.forEach(function (item, i) {
        setTimeout(function () {
          item.segs.forEach(function (s) { s.el.style.flexGrow = String(s.grow); });
          if (item.strong) countUp(item, 1500);
          if (item.row.classList.contains('is-self')) {
            setTimeout(function () { item.row.classList.add('sb-flash'); }, 1550);
          }
        }, i * 420);
      });
    }

    arm();
    onceVisible(board, play);
  })();
})();

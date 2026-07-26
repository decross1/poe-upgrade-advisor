/* Stack-agnostic verdict card renderer + bench timing.
 *
 * Protocol (shared by Electron and Tauri hosts):
 *   in : window 'bench-trigger' CustomEvent, detail = { seq, fixture }
 *        (detail.clipboard_ms is set by the host after a real platform
 *        clipboard read and is echoed back verbatim in the report)
 *   out: window.__BENCH_REPORT__(type, data)
 *          type 'render'  -> after the triggered card has painted
 *          type 'painted' -> initial card painted (cold start marker)
 *
 * The render timing is measured with performance.now() around the DOM update
 * and confirmed with a double requestAnimationFrame, i.e. the browser has
 * actually committed a frame containing the new card.
 */
(function () {
  'use strict';

  var BAR_FULL_SCALE_PCT = 10; // |delta| >= 10% fills half the track

  function report(type, data) {
    if (typeof window.__BENCH_REPORT__ === 'function') {
      window.__BENCH_REPORT__(type, data || {});
    }
  }

  function fmtDelta(v) {
    var sign = v > 0 ? '+' : v < 0 ? '−' : '±';
    return sign + Math.abs(v).toFixed(1) + '%';
  }

  function arrow(v) {
    return v > 0 ? '▲' : v < 0 ? '▼' : '●';
  }

  function setDelta(barEl, numEl, v) {
    var mag = Math.min(Math.abs(v) / BAR_FULL_SCALE_PCT, 1) * 50; // % of track
    barEl.className = 'bar ' + (v > 0 ? 'pos' : v < 0 ? 'neg' : 'flat');
    barEl.style.left = v < 0 ? 50 - mag + '%' : '50%';
    barEl.style.width = mag + '%';
    numEl.textContent = arrow(v) + ' ' + fmtDelta(v);
    numEl.style.color =
      v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--flat)';
  }

  function verdictWord(v) {
    return v === 'CANT_EVALUATE' ? "CAN'T EVALUATE" : v;
  }

  function renderCard(fixture) {
    var verdictEl = document.getElementById('verdict');
    verdictEl.textContent = verdictWord(fixture.verdict);
    verdictEl.className = 'verdict ' + fixture.verdict.toLowerCase();

    setDelta(
      document.getElementById('bar-off'),
      document.getElementById('num-off'),
      fixture.offense_delta_pct
    );
    setDelta(
      document.getElementById('bar-def'),
      document.getElementById('num-def'),
      fixture.defense_delta_pct
    );

    document.getElementById('sentence').textContent = fixture.sentence;

    var chips = document.getElementById('chips');
    chips.textContent = '';
    (fixture.assumptions || []).forEach(function (a) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip';
      chip.textContent = typeof a === 'string' ? a : JSON.stringify(a);
      chips.appendChild(chip);
    });
  }

  function afterTwoFrames(cb) {
    requestAnimationFrame(function () {
      requestAnimationFrame(cb);
    });
  }

  var initialPaintDone = false;

  function handleTrigger(detail) {
    var t0 = performance.now();
    renderCard(detail.fixture);
    afterTwoFrames(function () {
      var t1 = performance.now();
      report('render', {
        seq: detail.seq,
        clipboard_ms: detail.clipboard_ms,
        render_ms: t1 - t0,
      });
    });
  }

  window.addEventListener('bench-trigger', function (e) {
    handleTrigger(e.detail || {});
  });

  // "Open details" and chip taps are affordances only in the bench; record
  // that they were hit without doing network work (the real overlay deep-
  // links the web app).
  document.getElementById('details').addEventListener('click', function () {
    report('details-tapped', {});
  });
  document.getElementById('chips').addEventListener('click', function (e) {
    if (e.target && e.target.classList.contains('chip')) {
      report('chip-tapped', { assumption: e.target.textContent });
    }
  });

  // Initial paint = cold start marker. The host sends the first trigger with
  // seq 0 right after load; if none arrives (manual debugging) render a
  // placeholder so the window is not blank.
  window.__BENCH_HANDLE_TRIGGER__ = handleTrigger;
  window.addEventListener('DOMContentLoaded', function () {
    afterTwoFrames(function () {
      if (!initialPaintDone) {
        initialPaintDone = true;
        report('painted', {});
      }
    });
  });
})();

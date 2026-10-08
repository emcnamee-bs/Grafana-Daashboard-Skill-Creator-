/* Sample tile payloads (same shape as app.tile_payload) used by viewer_harness.html. */
(function () {
  var COL = { status: { ok: '#2f81f7', warn: '#d29922', fail: '#f85149', idle: '#6e7681', building: '#58a6ff' },
              health: { up: '#3fb950', degraded: '#d29922', down: '#f85149', unknown: '#6e7681' }, accent: '#4da3ff', text: '#e8eefc', muted: '#8fa6c8' };
  var NOW = 1791400000;
  function series(n, step, f) { var a = []; for (var i = 0; i < n; i++) a.push([NOW - (n - 1 - i) * step, f(i)]); return a; }
  function kpis() { return [{ label: 'ERR 7D', value: '0.5%', state: 'ok', explain: 'Share of runs in the last 7 days that ended in an error.' }, { label: 'STREAK', value: '128', state: null, explain: null }]; }
  function chart(title, kind, f, extra) {
    var c = { title: title, subtitle: 'errors / 30 min', kind: kind, y_max: null, span_label: '12h', points: series(24, 1800, f), history: null, history_label: '',
              kpis: kpis(), explain: title + ' canary: failed runs per 30 minutes.', breakdown: null };
    for (var k in (extra || {})) c[k] = extra[k];
    return c;
  }
  function members(n) { var a = []; for (var i = 0; i < n; i++) a.push({ name: 'container-' + (i + 1), state: i % 5 === 4 ? 'degraded' : 'up', what: 'Does thing number ' + (i + 1) + ' for the host' }); return a; }
  function health(n, withDetail) { var a = []; for (var i = 0; i < n; i++) a.push({ name: 'Part ' + (i + 1), state: ['up', 'degraded', 'down', 'unknown'][i % 4], explain: 'Part ' + (i + 1) + ' answers its health check.', detail: withDetail ? { why: 'Needs a look.', items: members(12) } : null }); return a; }

  var full = { colors: COL, name: 'Canaries', status: 'warn', status_label: '5 FAILING', branch: 'main', activity: 'idle · 16d+',
    task: 'PR #44: Add HTTP notice intake to failure-log-capture', summary: 'Always-on checks that provision, update and play content on test players.',
    stats: [
      { label: 'Failures 24h', value: '7', trend: null, explain: 'Failed canary runs in the last 24 hours.', detail: { why: 'Mostly Update probes.', items: [] } },
      { label: 'Checks failing', value: '5', trend: 'up', explain: 'Checks reporting consecutive errors.', detail: null },
      { label: 'Open PRs', value: '1', trend: null, explain: null, detail: null },
      { label: 'Containers', value: '5', trend: null, explain: 'Docker containers on the host.', detail: { why: '4 of 5 healthy', items: members(5) } }],
    health: health(4, false).map(function (h, i) { if (i === 3) h.detail = { why: '2 canaries report consecutive failures.', items: [] }; return h; }),
    charts: [
      chart('Provisioning', 'bar', function (i) { return i % 7 === 3 ? 2 : 0; },
            { history: series(56, 10800, function (i) { return i % 9 === 4 ? 3 : 0; }), history_label: '7d',
              breakdown: { ok_pct: 99.5, err_pct: 0.5, total: 1840, worst: [{ label: 'Tue 14:00', value: '3 err' }, { label: 'Wed 02:00', value: '3 err' }] } }),
      chart('Update', 'bar', function (i) { return i % 3 === 0 ? 4 : 1; }, { history: series(56, 10800, function (i) { return (i * 7) % 5; }), history_label: '7d' }),
      chart('Content', 'line', function (i) { return 10 + (i % 6); })] };

  var minimal = { colors: COL, name: 'Old tile', status: 'idle', status_label: 'idle', branch: '-', activity: 'idle', task: null, summary: null,
    stats: [], health: [], charts: [{ title: 'One point', subtitle: '', kind: 'line', y_max: null, span_label: '12h', points: [[NOW, 1]], history: null, history_label: '', kpis: [], explain: null, breakdown: null }] };

  // Hostile strings, cut to the lengths the server really allows (app.validate caps every field), so layout checks model what can arrive.
  // The fields with generous caps (summary 240, explain 200, why 240, what 120, task 90) carry the whole injection string.
  var bad = '"\'><img src=x onerror=alert(1)></style><script>alert(2)</script>';
  function cap(n) { return (bad + bad + bad + bad + bad).slice(0, n); }
  var long = function (ch, n) { return ch.repeat(n); };
  var hostile = { colors: COL, name: cap(28), status: 'fail', status_label: cap(14), branch: cap(40), activity: 'idle · ' + cap(24), task: cap(90), summary: cap(240),
    stats: [{ label: cap(16), value: cap(12), trend: 'down', explain: cap(200), detail: { why: cap(240), items: [{ name: cap(24), state: 'down', what: cap(120) }] } }],
    health: [{ name: long('y', 18), state: 'down', explain: cap(200), detail: { why: cap(240), items: members(12) } }],
    charts: [{ title: long('a', 22), subtitle: cap(26), kind: 'bar', y_max: null, span_label: cap(8), points: [], history: [], history_label: '', kpis: [{ label: cap(12), value: cap(10), state: 'bad', explain: cap(200) }], explain: cap(200), breakdown: { worst: [{ label: cap(24), value: cap(12) }] } },
             { title: 'zeros', subtitle: '', kind: 'bar', y_max: null, span_label: '12h', points: series(24, 1800, function () { return 0; }), history: series(5, 3600, function () { return 0; }), history_label: '7d', kpis: [], explain: null, breakdown: { ok_pct: 100, err_pct: 0, worst: [] } }] };

  var big = { colors: COL, name: 'Maximum tile', status: 'warn', status_label: '9 DEGRADED', branch: 'feature/a-fairly-long-branch-name', activity: 'active · now',
    task: 'A long current task description that goes on for quite a while to stress the left column of the square view',
    summary: 'A long summary of what this tile is and why it exists, written to be as wordy as the validated limits allow so the layout has to cope with a maximal amount of text in the left column.',
    stats: [0, 1, 2, 3, 4, 5].map(function (i) { return { label: 'Stat ' + i, value: String(1000 + i), trend: i % 2 ? 'up' : null, explain: 'Explains stat ' + i + '.', detail: { why: 'Because.', items: members(12) } }; }),
    health: health(8, true),
    charts: [0, 1, 2, 3].map(function (i) { return chart('Chart ' + i, i % 2 ? 'line' : 'bar', function (k) { return (k * (i + 3)) % 7; }, { history: series(400, 1800, function (k) { return (k * (i + 2)) % 9; }), history_label: '7d', breakdown: { ok_pct: 97.25, err_pct: 2.75, total: 123456, worst: [1, 2, 3, 4, 5].map(function (w) { return { label: 'Mon 0' + w + ':00', value: w + ' err' }; }) } }); }) };

  window.FIXTURES = { full: full, minimal: minimal, hostile: hostile, big: big };
})();

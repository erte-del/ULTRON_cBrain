// ACC lap viewer: Laps, Lap view, Compare, Live. Plain JS, no build step.
(function () {
  const app = document.getElementById('app');
  let cleanup = [];          // things to stop when the page changes (timers, sockets, charts)

  // ---------- helpers ----------
  function h(tag, props, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
    }
    kids.flat().forEach((c) => c != null && e.append(c.nodeType ? c : document.createTextNode(c)));
    return e;
  }
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  async function api(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error((await r.text().catch(() => '')) || r.statusText);
    return r.json();
  }
  const fmtMs = (ms) => { if (!ms || ms <= 0) return '–'; const m = Math.floor(ms / 60000); return m + ':' + ((ms % 60000) / 1000).toFixed(3).padStart(6, '0'); };
  const fmtS = (s) => fmtMs(Math.round(s * 1000));
  const sign = (v, d = 3) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const num = (v, d = 0) => (v === null || v === undefined ? '–' : (+v).toFixed(d));
  const grid = (n) => Array.from({ length: n }, (_, i) => i / (n - 1));
  function show(...nodes) { app.replaceChildren(...nodes.flat()); }
  function fail(e) { show(h('div', { class: 'err' }, 'Something went wrong: ' + e.message)); }
  function bandsOf(info) {
    if (!info || !info.segments) return [];
    return info.segments.filter((s) => s.kind === 'corner' && s.end > s.start).map((s) => ({ name: s.name, start: s.start, end: s.end }));
  }

  // ---------- header status ----------
  const pill = document.getElementById('pill');
  async function pollStatus() {
    try {
      const s = await api('/api/status');
      document.getElementById('banner').hidden = s.mode !== 'mock';
      pill.textContent = s.status === 'live' ? (s.track || 'live') + ' · ' + (s.car || '') : s.message.replace(/\.$/, '');
      pill.className = 'pill ' + (s.status === 'live' ? 'live' : 'bad');
    } catch (e) { pill.textContent = 'viewer offline'; pill.className = 'pill bad'; }
  }
  pollStatus(); setInterval(pollStatus, 2500);

  // ---------- Laps ----------
  async function pageLaps() {
    const sel = new Set();
    const wrap = h('div');
    let lastKey = '', filter = { track: '', car: '' };
    show(h('h1', {}, 'Laps'), h('div', { class: 'sub' }, 'Every completed lap is saved here. Pick two to compare, or compare any lap with your best.'), wrap);

    async function refresh() {
      const data = await api('/api/laps?limit=300');
      const key = data.laps.map((l) => l.id).join(',') + filter.track + filter.car + [...sel].join();
      if (key === lastKey) return;
      lastKey = key;
      draw(data.laps);
    }
    function draw(all) {
      const tracks = [...new Set(all.map((l) => l.track))], cars = [...new Set(all.map((l) => l.car))];
      const laps = all.filter((l) => (!filter.track || l.track === filter.track) && (!filter.car || l.car === filter.car));
      const bestOf = {};
      all.forEach((l) => { if (l.clean && l.valid) { const k = l.track + '|' + l.car; if (!bestOf[k] || l.lap_time_ms < bestOf[k].lap_time_ms) bestOf[k] = l; } });
      const pick = (name, opts, cur) => h('select', { onchange: (e) => { filter[name] = e.target.value; lastKey = ''; draw(all); } },
        h('option', { value: '' }, 'All ' + name + 's'), opts.map((o) => h('option', { value: o, selected: o === cur }, o)));
      const two = [...sel];
      const cmp = h('button', { class: 'primary', disabled: two.length !== 2, onclick: () => (location.hash = '#/compare/' + two[0] + '/' + two[1]) }, 'Compare selected');
      const rows = laps.map((l) => {
        const best = bestOf[l.track + '|' + l.car];
        const isBest = best && best.id === l.id;
        const cb = h('input', { type: 'checkbox', checked: sel.has(l.id), onclick: (e) => e.stopPropagation(), onchange: (e) => {
          if (e.target.checked) { sel.add(l.id); if (sel.size > 2) sel.delete([...sel][0]); } else sel.delete(l.id);
          lastKey = ''; draw(all);
        } });
        return h('tr', { class: 'click' + (isBest ? ' best' : ''), onclick: () => (location.hash = '#/lap/' + l.id) },
          h('td', {}, cb), h('td', { class: 'n' }, l.id), h('td', { class: 'n' }, l.lap_number), h('td', { class: 'n' }, l.lap_time),
          l.sectors_ms.map((s) => h('td', { class: 'n' }, fmtMs(s))),
          h('td', {}, l.track), h('td', {}, l.car),
          h('td', {}, isBest ? h('span', { class: 'tag good' }, 'best') : null, !l.valid ? h('span', { class: 'tag bad' }, 'invalid') : null,
            !l.clean ? h('span', { class: 'tag bad' }, 'pit/partial') : null),
          h('td', {}, when(l.created_at)),
          h('td', {}, best && !isBest ? h('a', { href: '#/compare/' + l.id + '/' + best.id, onclick: (e) => e.stopPropagation() }, 'vs best') : ''));
      });
      wrap.replaceChildren(
        h('div', { class: 'row' }, pick('track', tracks, filter.track), pick('car', cars, filter.car), cmp),
        laps.length ? h('div', { class: 'card scroll' }, h('table', {},
          h('thead', {}, h('tr', {}, ['', 'ID', 'Lap', 'Time', 'S1', 'S2', 'S3', 'Track', 'Car', '', 'When', ''].map((t, i) => h('th', { class: i > 0 && i < 7 ? 'n' : '' }, t)))),
          h('tbody', {}, rows))) : h('div', { class: 'empty' }, 'No laps yet. Drive a lap in ACC (or run with --mock) and it will show up here within a few seconds.'));
    }
    await refresh();
    const t = setInterval(() => refresh().catch(() => {}), 3000);
    cleanup.push(() => clearInterval(t));
  }

  // ---------- map ----------
  function drawMap(canvas, points, pos) {
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, hh = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = hh * dpr;
    const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, hh);
    if (!points || points.length < 3) return;
    const xs = points.map((p) => p[0]), zs = points.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minZ = Math.min(...zs), maxZ = Math.max(...zs);
    const s = Math.min((w - 20) / (maxX - minX || 1), (hh - 20) / (maxZ - minZ || 1));
    const ox = (w - (maxX - minX) * s) / 2, oz = (hh - (maxZ - minZ) * s) / 2;
    const P = (p) => [ox + (p[0] - minX) * s, oz + (maxZ - p[1]) * s];
    ctx.strokeStyle = css('--muted'); ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.beginPath();
    points.forEach((p, i) => { const [x, y] = P(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.closePath(); ctx.stroke();
    if (pos !== null && pos !== undefined) {
      const i = Math.min(points.length - 1, Math.max(0, Math.round(pos * points.length)) % points.length);
      const [x, y] = P(points[i]);
      ctx.fillStyle = css('--accent'); ctx.beginPath(); ctx.arc(x, y, 6, 0, 7); ctx.fill();
    }
  }

  // ---------- Lap view ----------
  async function pageLap(id) {
    const lap = await api('/api/lap/' + id);
    const t = lap.trace, n = t.t.length, x = grid(n);
    const toggles = { slip: false, tc: false, g: false, rpm: false };
    const host = h('div'), mapCanvas = h('canvas', { class: 'map' }), cornerBox = h('div');
    let charts = null;
    const S = (label, y, color, o) => Object.assign({ label, x, y, color }, o || {});
    function panels() {
      const P = [
        { title: 'Speed', unit: 'km/h', min: 0, height: 150, format: (v) => v.toFixed(0), series: [S('', t.speed, css('--speed'))] },
        { title: 'Brake', min: 0, max: 1.05, height: 90, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100), series: [S('', t.brake, css('--brake'), { fill: true })] },
        { title: 'Throttle', min: 0, max: 1.05, height: 90, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100), series: [S('', t.throttle, css('--throttle'), { fill: true })] },
        { title: 'Steering', symmetric: true, height: 90, format: (v) => v.toFixed(2), series: [S('', t.steer, css('--steer'))] },
        { title: 'Gear', min: 0, max: 7, height: 80, format: (v) => v.toFixed(0), tickFormat: (v) => v, series: [S('', t.gear, css('--gear'), { step: true })] },
      ];
      if (toggles.rpm) P.push({ title: 'RPM', min: 0, height: 90, format: (v) => v.toFixed(0), series: [S('', t.rpm, css('--b'))] });
      if (toggles.slip) P.push({ title: 'Tyre slip (max wheel)', min: 0, height: 90, format: (v) => v.toFixed(2), series: [S('', t.slip, css('--warn'))] });
      if (toggles.tc) P.push({ title: 'TC / ABS activity', min: 0, max: 1, height: 80, format: (v) => v.toFixed(2), series: [S('TC', t.tc, css('--b')), S('ABS', t.abs, css('--a'))] });
      if (toggles.g) P.push({ title: 'G forces', symmetric: true, height: 100, format: (v) => v.toFixed(2), series: [S('lat', t.lat_g, css('--a')), S('long', t.lon_g, css('--b'))] });
      return P;
    }
    function build() {
      if (charts) charts.destroy();
      charts = new LapCharts(host, { panels: panels(), bands: bandsOf(lap.track_info), lengthM: lap.length_m,
        onHover: (p) => drawMap(mapCanvas, lap.track_info.map, p) });
      requestAnimationFrame(() => drawMap(mapCanvas, lap.track_info.map, null));
    }
    const tg = (key, label) => h('label', {}, h('input', { type: 'checkbox', onchange: (e) => { toggles[key] = e.target.checked; build(); } }), ' ' + label);
    const cm = lap.corners_metrics || [];
    cornerBox.append(cm.length ? h('div', { class: 'card scroll' }, h('table', {},
      h('thead', {}, h('tr', {}, ['Corner', 'Entry km/h', 'Min km/h', 'Brake start (m before apex)', 'Peak brake', 'Trail s', 'Throttle pickup (lap pos)', 'Peak lat G', 'Peak long G', 'Time s'].map((c, i) => h('th', { class: i ? 'n' : '' }, c)))),
      h('tbody', {}, cm.map((c) => h('tr', {}, h('td', {}, c.name), [[c.entry_kmh, 0], [c.min_kmh, 0], [c.brake_dist_m, 0], [c.brake_peak, 2], [c.trail_s, 2], [c.throttle_pickup_pos, 3], [c.peak_lat_g, 2], [c.peak_lon_g, 2], [c.time_s, 2]].map(([v, d]) => h('td', { class: 'n' }, num(v, d)))))))) : h('div', { class: 'empty' }, 'No corner table for this track yet.'));
    const events = (lap.events || []).map((e) => h('tr', {}, h('td', {}, e.type), h('td', {}, e.corner || ''), h('td', { class: 'n' }, (e.pos * 100).toFixed(1) + '%'), h('td', { class: 'n' }, e.duration_s + ' s'), h('td', {}, e.severity)));
    show(
      h('div', { class: 'row' }, h('a', { href: '#/' }, '← Laps'),
        lap.id > 1 ? h('a', { href: '#/lap/' + (lap.id - 1) }, 'previous') : null, h('a', { href: '#/lap/' + (lap.id + 1) }, 'next'),
        h('a', { href: '#/compare/' + lap.id + '/best' }, 'compare with best')),
      h('h1', {}, lap.lap_time + '  ·  lap ' + lap.lap_number),
      h('div', { class: 'sub' }, [lap.track, lap.car, when(lap.created_at), lap.compound, lap.valid ? '' : 'invalid lap', lap.clean ? '' : 'pit/partial lap'].filter(Boolean).join(' · ') +
        '   Sectors ' + lap.sectors_ms.map(fmtMs).join(' / ')),
      h('div', { class: 'row' }, 'Extra charts:', tg('rpm', 'RPM'), tg('slip', 'Tyre slip'), tg('tc', 'TC / ABS'), tg('g', 'G forces')),
      h('div', { class: 'grid2' }, host, h('div', {}, h('div', { class: 'card' }, mapCanvas), events.length ? h('div', { class: 'card', style: 'margin-top:14px' }, h('b', {}, 'Events'), h('table', {}, h('thead', {}, h('tr', {}, ['Type', 'Where', 'Lap pos', 'Lasted', ''].map((t) => h('th', {}, t)))), h('tbody', {}, events))) : null)),
      h('h2', {}, 'Corners'), cornerBox);
    build();
    cleanup.push(() => charts && charts.destroy());
  }

  // ---------- Compare ----------
  async function pageCompare(a, b) {
    const cmp = await api('/api/compare?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b));
    const [A, B] = await Promise.all([api('/api/lap/' + cmp.a.id), api('/api/lap/' + cmp.b.id)]);
    const ta = A.trace, tb = B.trace, n = ta.t.length, x = grid(n);
    const ca = css('--a'), cb = css('--b');
    const two = (label, key, o) => Object.assign({}, o, { series: [
      { label: 'A', x, y: ta[key], color: ca, fill: o && o.fill, width: 1.8 }, { label: 'B', x, y: tb[key], color: cb, fill: o && o.fill, width: 1.8 }] });
    const sum = cmp.summary, total = sum.total_delta_s;
    const host = h('div');
    const charts = new LapCharts(host, { bands: bandsOf(cmp.track_info), lengthM: A.length_m, panels: [
      two('', 'speed', { title: 'Speed', unit: 'km/h', min: 0, height: 150, format: (v) => v.toFixed(0) }),
      two('', 'brake', { title: 'Brake', min: 0, max: 1.05, height: 90, fill: true, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100) }),
      two('', 'throttle', { title: 'Throttle', min: 0, max: 1.05, height: 90, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100) }),
      two('', 'steer', { title: 'Steering', symmetric: true, height: 90, format: (v) => v.toFixed(2) }),
      { title: 'Time delta A − B', unit: 's', symmetric: true, height: 120, format: (v) => sign(v), series: [{ label: 'Δ', x, y: cmp.delta, color: css('--fg'), delta: true, width: 1.4 }] },
    ] });
    cleanup.push(() => charts.destroy());

    // time lost per corner / straight, in lap order
    const segs = sum.biggest.slice().sort((p, q) => Math.abs(q.delta_s) - Math.abs(p.delta_s));
    const maxAbs = Math.max(0.05, ...segs.map((s) => Math.abs(s.delta_s)));
    const bars = h('table', { class: 'bars' }, h('tbody', {}, segs.map((s) => h('tr', {}, h('td', {}, s.name), h('td', { class: 'n ' + (s.delta_s > 0 ? 'loss' : 'gain') }, sign(s.delta_s)),
      h('td', { class: 'bar' }, h('div', { class: 'bar-wrap' }, h('div', { class: 'mid' }, ''),
        h('i', { style: 'background:' + (s.delta_s > 0 ? css('--loss') : css('--gain')) + ';' + (s.delta_s > 0 ? 'left:50%;width:' + (s.delta_s / maxAbs * 50) + '%' : 'right:50%;width:' + (-s.delta_s / maxAbs * 50) + '%') }))),
      h('td', { class: 'n' }, s.a_min_kmh !== undefined ? s.a_min_kmh.toFixed(0) + ' / ' + s.b_min_kmh.toFixed(0) + ' km/h' : '')))));

    const cell = (v, d = 0) => h('td', { class: 'n' }, num(v, d));
    const rows = cmp.braking.map((r) => {
      const flag = r.brake === 'earlier' ? 'earlier' : r.brake === 'later' ? 'later' : '';
      return h('tr', {}, h('td', {}, r.corner),
        cell(r.a.brake_dist_m), cell(r.b.brake_dist_m), h('td', { class: 'n ' + flag }, r.brake_diff_m === null ? '–' : (r.brake_diff_m > 0 ? '+' : '') + r.brake_diff_m.toFixed(0) + ' m ' + (flag ? '(' + flag + ')' : '')),
        cell(r.a.brake_peak, 2), cell(r.b.brake_peak, 2), cell(r.a.trail_s, 2), cell(r.b.trail_s, 2),
        cell(r.a.entry_kmh), cell(r.b.entry_kmh), cell(r.a.min_kmh), cell(r.b.min_kmh), cell(r.a.pickup_after_min_m), cell(r.b.pickup_after_min_m));
    });
    const lapsList = (await api('/api/laps?track=' + encodeURIComponent(A.track) + '&car=' + encodeURIComponent(A.car) + '&limit=100')).laps;
    const pickLap = (cur, which) => h('select', { onchange: (e) => (location.hash = '#/compare/' + (which === 'a' ? e.target.value + '/' + cmp.b.id : cmp.a.id + '/' + e.target.value)) },
      lapsList.map((l) => h('option', { value: l.id, selected: l.id === cur }, '#' + l.id + '  lap ' + l.lap_number + '  ' + l.lap_time)));
    show(
      h('div', { class: 'row' }, h('a', { href: '#/' }, '← Laps')),
      h('h1', {}, 'Compare'),
      h('div', { class: 'row' }, h('span', {}, h('i', { class: 'dot', style: 'background:' + ca }), 'A ', pickLap(cmp.a.id, 'a')), h('span', {}, h('i', { class: 'dot', style: 'background:' + cb }), 'B ', pickLap(cmp.b.id, 'b')),
        h('button', { onclick: () => (location.hash = '#/compare/' + cmp.b.id + '/' + cmp.a.id) }, 'Swap')),
      h('div', { class: 'legend' },
        h('div', {}, h('div', { class: 'sub' }, 'Lap A'), h('b', {}, cmp.a.lap_time)), h('div', {}, h('div', { class: 'sub' }, 'Lap B'), h('b', {}, cmp.b.lap_time)),
        h('div', {}, h('div', { class: 'sub' }, 'A vs B'), h('span', { class: 'delta-big ' + (total > 0 ? 'loss' : 'gain') }, sign(total) + ' s')),
        h('div', {}, h('div', { class: 'sub' }, sum.most_time_lost ? 'Most time lost' : 'Most time gained'), h('b', { style: 'font-size:15px' }, sum.most_time_lost || sum.most_time_gained || 'about equal'))),
      host,
      h('h2', {}, 'Where the time went (A vs B)'), h('div', { class: 'card scroll' }, bars),
      h('h2', {}, 'Braking table'),
      h('div', { class: 'sub' }, 'Brake start is metres before the apex. “earlier” / “later” compares A with B (needs 5 m or more).'),
      h('div', { class: 'card scroll' }, h('table', {},
        h('thead', {}, h('tr', {}, ['Corner', 'Brake A', 'Brake B', 'A vs B', 'Peak A', 'Peak B', 'Trail A s', 'Trail B s', 'Entry A', 'Entry B', 'Min A', 'Min B', 'Pickup A m', 'Pickup B m'].map((c, i) => h('th', { class: i ? 'n' : '' }, c)))),
        h('tbody', {}, rows))));
  }

  // ---------- Live ----------
  async function pageLive() {
    const stats = h('div', { class: 'live-top' }), tyres = h('div', { class: 'tyres' }), alerts = h('div', { class: 'alerts' }), host = h('div'), note = h('div', { class: 'sub' }, 'Connecting…');
    show(h('h1', {}, 'Live'), note, stats, h('div', { class: 'grid2' }, host, h('div', {}, h('div', { class: 'card' }, h('b', {}, 'Tyres (core °C)'), h('div', { style: 'height:8px' }), tyres), h('div', { class: 'card', style: 'margin-top:14px' }, h('b', {}, 'Alerts'), alerts))));
    let refId = null, ref = null, limits = { temp_c: [70, 105] };
    try { limits = (await api('/api/tool/get_tyre_report')).limits || limits; } catch (e) { /* defaults */ }
    const empty = { x: [], y: [] };
    const charts = new LapCharts(host, { panels: [
      { title: 'Speed', unit: 'km/h', min: 0, height: 140, format: (v) => v.toFixed(0), series: [{ label: 'ref', color: css('--muted'), dash: [4, 4], width: 1.2, ...empty }, { label: 'now', color: css('--speed'), ...empty }] },
      { title: 'Brake', min: 0, max: 1.05, height: 90, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100), series: [{ label: 'ref', color: css('--muted'), dash: [4, 4], width: 1.2, ...empty }, { label: 'now', color: css('--brake'), fill: true, ...empty }] },
      { title: 'Throttle', min: 0, max: 1.05, height: 90, format: (v) => Math.round(v * 100) + '%', tickFormat: (v) => Math.round(v * 100), series: [{ label: 'ref', color: css('--muted'), dash: [4, 4], width: 1.2, ...empty }, { label: 'now', color: css('--throttle'), fill: true, ...empty }] },
    ] });
    const scheme = (proto) => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + proto;
    const ws = new WebSocket(scheme('/ws/live')), aw = new WebSocket(scheme('/ws/alerts'));
    cleanup.push(() => { ws.close(); aw.close(); charts.destroy(); });
    aw.onmessage = (ev) => {
      const a = JSON.parse(ev.data);
      alerts.prepend(h('div', { class: a.type }, h('span', { class: 't' }, a.at.slice(11)), a.message));
      while (alerts.children.length > 40) alerts.lastChild.remove();
    };
    const stat = (k, v, u, cls) => h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v ' + (cls || '') }, v, u ? h('span', { class: 'u' }, ' ' + u) : null));
    ws.onmessage = async (ev) => {
      const m = JSON.parse(ev.data), s = m.state;
      if (!s.live) {
        note.textContent = s.message || 'Waiting for ACC…';
        stats.replaceChildren(); tyres.replaceChildren();
        return;
      }
      note.textContent = [s.track, s.car].join(' · ');
      const d = s.delta_to_best_s;
      stats.replaceChildren(
        stat('Speed', s.speed_kmh, 'km/h'), stat('Gear', s.gear <= 0 ? (s.gear < 0 ? 'R' : 'N') : s.gear), stat('Lap', s.lap, s.lap_time),
        stat('Corner', s.corner || '–'), stat('Δ best', d === null ? '–' : sign(d, 2), 's', d === null ? '' : d > 0 ? 'loss' : 'gain'),
        stat('Fuel', num(s.fuel_l, 1), 'L'), stat('Fuel laps', num(s.fuel_laps_left, 1)));
      tyres.replaceChildren(...['FL', 'FR', 'RL', 'RR'].map((w) => {
        const t = s.tyre_temp_c[w], cls = t < limits.temp_c[0] ? 'cold' : t > limits.temp_c[1] ? 'hot' : '';
        return h('div', { class: 'tyre ' + cls }, h('div', { class: 'sub' }, w), h('b', {}, t.toFixed(0)), s.tyre_psi[w].toFixed(1) + ' psi');
      }));
      if (m.ref_id !== refId) { refId = m.ref_id; ref = refId ? (await api('/api/lap/' + refId)).trace : null; }
      const tr = m.trace, rx = ref ? grid(ref.t.length) : [];
      charts.update({ panels: charts.opts.panels.map((p, i) => {
        const key = ['speed', 'brake', 'throttle'][i];
        return { ...p, series: [{ ...p.series[0], x: rx, y: ref ? ref[key] : [] }, { ...p.series[1], x: tr.pos, y: tr[key] }] };
      }) });
    };
  }

  // ---------- router ----------
  async function route() {
    cleanup.forEach((f) => { try { f(); } catch (e) { /* already gone */ } });
    cleanup = [];
    const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
    document.querySelectorAll('nav a').forEach((a) => a.classList.toggle('on', a.dataset.nav === (parts[0] === 'live' ? 'live' : 'laps')));
    window.scrollTo(0, 0);
    try {
      if (parts[0] === 'lap' && parts[1]) await pageLap(parts[1]);
      else if (parts[0] === 'compare' && parts[1] && parts[2]) await pageCompare(parts[1], parts[2]);
      else if (parts[0] === 'live') await pageLive();
      else await pageLaps();
    } catch (e) { fail(e); }
  }
  window.addEventListener('hashchange', route);
  route();
})();

// LapCharts: stacked canvas panels that share one x axis (lap position, 0..1). No dependencies.
//
//   new LapCharts(rootEl, {
//     panels: [{ title, unit, min, max, symmetric, format, height,
//                series: [{ label, x, y, color, fill, step, width, dash, delta }] }],
//     bands:  [{ name, start, end }],        // corner windows, shaded behind every panel, named along the top
//     lengthM: 7004,                         // x axis in km when known
//     onHover: (x|null) => {}                // lap position under the mouse
//   })
//
// Drag to zoom, double-click to reset. A hover line runs through every panel with each series' value.

(function () {
  const M = { left: 56, right: 14 };

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function niceTicks(lo, hi, n) {
    const span = hi - lo || 1;
    const raw = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }

  // value of a series at x (linear between points); null outside its range
  function valueAt(s, x) {
    const xs = s.x, ys = s.y;
    if (!xs || !xs.length || x < xs[0] || x > xs[xs.length - 1]) return null;
    let lo = 0, hi = xs.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (xs[mid] <= x) lo = mid; else hi = mid;
    }
    if (s.step) return ys[lo];
    const span = xs[hi] - xs[lo];
    return span > 0 ? ys[lo] + ((ys[hi] - ys[lo]) * (x - xs[lo])) / span : ys[lo];
  }

  class LapCharts {
    constructor(root, opts) {
      this.root = root;
      this.opts = opts;
      this.view = [0, 1];
      this.hover = null;
      this.drag = null;
      this.pending = false;
      root.classList.add('lapcharts');
      this.build();
      this.ro = new ResizeObserver(() => this.draw());
      this.ro.observe(root);
    }

    build() {
      const o = this.opts;
      this.root.innerHTML = '';
      this.bandCanvas = this.addCanvas('band', 28);
      this.panels = o.panels.map((p) => {
        const wrap = document.createElement('div');
        wrap.className = 'panel';
        const head = document.createElement('div');
        head.className = 'panel-head';
        const title = document.createElement('span');
        title.className = 'panel-title';
        title.textContent = p.title + (p.unit ? ' (' + p.unit + ')' : '');
        const read = document.createElement('span');
        read.className = 'panel-read';
        head.append(title, read);
        wrap.appendChild(head);
        this.root.appendChild(wrap);
        const canvas = this.addCanvas('', p.height || 120, wrap);
        return { def: p, canvas, read };
      });
      this.axisCanvas = this.addCanvas('axis', 24);
      const hint = document.createElement('div');
      hint.className = 'chart-hint';
      hint.textContent = 'Drag to zoom · double-click to reset';
      this.root.appendChild(hint);
    }

    addCanvas(cls, height, parent) {
      const c = document.createElement('canvas');
      c.className = cls;
      c.style.height = height + 'px';
      c.style.width = '100%';
      c.dataset.h = height;
      (parent || this.root).appendChild(c);
      c.addEventListener('mousemove', (e) => this.onMove(e, c));
      c.addEventListener('mouseleave', () => { this.hover = null; this.drag = null; this.opts.onHover && this.opts.onHover(null); this.schedule(); });
      c.addEventListener('mousedown', (e) => { this.drag = { a: this.xAt(e, c), b: this.xAt(e, c) }; });
      c.addEventListener('mouseup', () => this.endDrag());
      c.addEventListener('dblclick', () => { this.view = [0, 1]; this.schedule(); });
      return c;
    }

    update(opts) {
      Object.assign(this.opts, opts);
      this.panels.forEach((p, i) => { p.def = this.opts.panels[i]; });
      this.schedule();
    }

    destroy() { this.ro.disconnect(); this.root.innerHTML = ''; }

    xAt(e, canvas) {
      const r = canvas.getBoundingClientRect();
      const t = (e.clientX - r.left - M.left) / Math.max(1, r.width - M.left - M.right);
      return this.view[0] + Math.min(1, Math.max(0, t)) * (this.view[1] - this.view[0]);
    }

    onMove(e, c) {
      this.hover = this.xAt(e, c);
      if (this.drag) this.drag.b = this.hover;
      this.opts.onHover && this.opts.onHover(this.hover);
      this.schedule();
    }

    endDrag() {
      if (this.drag) {
        const [a, b] = [Math.min(this.drag.a, this.drag.b), Math.max(this.drag.a, this.drag.b)];
        if (b - a > 0.004) this.view = [a, b];
        this.drag = null;
        this.schedule();
      }
    }

    schedule() {
      if (this.pending) return;
      this.pending = true;
      requestAnimationFrame(() => { this.pending = false; this.draw(); });
    }

    setup(canvas) {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = +canvas.dataset.h;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      return { ctx, w, h };
    }

    px(x, w) { return M.left + ((x - this.view[0]) / (this.view[1] - this.view[0])) * (w - M.left - M.right); }

    draw() {
      const col = { fg: css('--fg', '#ddd'), muted: css('--muted', '#888'), grid: css('--grid', '#333'), band: css('--band', 'rgba(128,128,128,.08)') };
      this.drawBands(col);
      this.panels.forEach((p) => this.drawPanel(p, col));
      this.drawAxis(col);
    }

    bandsInView() { return (this.opts.bands || []).filter((b) => b.end >= this.view[0] && b.start <= this.view[1]); }

    drawBands(col) {
      const { ctx, w, h } = this.setup(this.bandCanvas);
      ctx.font = '11px system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      this.bandsInView().forEach((b, i) => {
        const x0 = Math.max(M.left, this.px(b.start, w)), x1 = Math.min(w - M.right, this.px(b.end, w));
        ctx.fillStyle = i % 2 ? 'rgba(128,128,128,.22)' : 'rgba(128,128,128,.12)';
        ctx.fillRect(x0, 4, x1 - x0, h - 8);
        ctx.fillStyle = col.fg;
        // the full name if it fits, else its first word, else a dot
        const label = [b.name, b.name.split(/[ /]/)[0]].find((t) => ctx.measureText(t).width + 6 <= x1 - x0);
        if (label) ctx.fillText(label, x0 + (x1 - x0 - ctx.measureText(label).width) / 2, h / 2);
        else if (x1 - x0 > 14) { ctx.fillStyle = col.muted; ctx.fillText('·', x0 + (x1 - x0) / 2 - 1, h / 2); }
      });
      if (this.hover !== null) this.hoverLine(ctx, w, h, col, true);
    }

    range(p) {
      const d = p.def;
      let lo = Infinity, hi = -Infinity;
      d.series.forEach((s) => {
        for (let i = 0; i < s.y.length; i++) {
          const x = s.x[i];
          if (x < this.view[0] || x > this.view[1]) continue;
          if (s.y[i] < lo) lo = s.y[i];
          if (s.y[i] > hi) hi = s.y[i];
        }
      });
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      if (d.symmetric) { const m = Math.max(Math.abs(lo), Math.abs(hi), 0.05); lo = -m; hi = m; }
      if (d.min !== undefined) lo = d.min;
      if (d.max !== undefined) hi = d.max;
      if (d.min === undefined && d.max === undefined) { const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; }
      if (hi === lo) hi = lo + 1;
      return [lo, hi];
    }

    drawPanel(p, col) {
      const { ctx, w, h } = this.setup(p.canvas);
      const top = 6, bottom = h - 6;
      const [lo, hi] = this.range(p);
      const y = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
      // corner shading
      this.bandsInView().forEach((b, i) => {
        if (i % 2) return;
        const x0 = Math.max(M.left, this.px(b.start, w)), x1 = Math.min(w - M.right, this.px(b.end, w));
        ctx.fillStyle = col.band;
        ctx.fillRect(x0, 0, x1 - x0, h);
      });
      // grid and y labels
      ctx.font = '11px system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'right';
      niceTicks(lo, hi, Math.max(2, Math.floor(h / 36))).forEach((v) => {
        const yy = y(v);
        ctx.strokeStyle = v === 0 && lo < 0 ? col.muted : col.grid;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(M.left, yy + 0.5); ctx.lineTo(w - M.right, yy + 0.5); ctx.stroke();
        ctx.fillStyle = col.muted;
        ctx.fillText((p.def.tickFormat || ((n) => +n.toFixed(2)))(v), M.left - 6, yy);
      });
      ctx.textAlign = 'left';
      // series
      ctx.save();
      ctx.beginPath(); ctx.rect(M.left, 0, w - M.left - M.right, h); ctx.clip();
      p.def.series.forEach((s) => this.drawSeries(ctx, s, y, w, lo, hi, col));
      if (this.drag) {
        const a = this.px(Math.min(this.drag.a, this.drag.b), w), b = this.px(Math.max(this.drag.a, this.drag.b), w);
        ctx.fillStyle = 'rgba(100,150,255,.18)';
        ctx.fillRect(a, 0, b - a, h);
      }
      ctx.restore();
      if (this.hover !== null) this.hoverLine(ctx, w, h, col, false);
      this.readout(p);
    }

    drawSeries(ctx, s, y, w, lo, hi, col) {
      const n = s.x.length;
      if (!n) return;
      const path = new Path2D();
      let started = false, last = null;
      for (let i = 0; i < n; i++) {
        if (s.x[i] < this.view[0] - 0.02 && s.x[Math.min(n - 1, i + 1)] < this.view[0] - 0.02) continue;
        if (s.x[i] > this.view[1] + 0.02 && last !== null && last > this.view[1] + 0.02) break;
        const xx = this.px(s.x[i], w), yy = y(s.y[i]);
        if (!started) { path.moveTo(xx, yy); started = true; }
        else if (s.step) { path.lineTo(xx, y(s.y[i - 1])); path.lineTo(xx, yy); }
        else path.lineTo(xx, yy);
        last = s.x[i];
      }
      if (!started) return;
      const base = y(Math.max(lo, Math.min(hi, 0)));
      if (s.delta) {            // time delta: red above zero (behind), green below (ahead)
        const zero = y(0);
        for (const [c, a, b] of [[css('--loss', '#e5484d'), 0, zero], [css('--gain', '#30a46c'), zero, 400]]) {
          ctx.save();
          ctx.beginPath(); ctx.rect(M.left, a, w, b - a); ctx.clip();
          const f = new Path2D(path);
          f.lineTo(this.px(s.x[n - 1], w), zero); f.lineTo(this.px(s.x[0], w), zero); f.closePath();
          ctx.fillStyle = c; ctx.globalAlpha = 0.35; ctx.fill(f);
          ctx.restore();
        }
      } else if (s.fill) {
        const f = new Path2D(path);
        f.lineTo(this.px(s.x[n - 1], w), base); f.lineTo(this.px(s.x[0], w), base); f.closePath();
        ctx.fillStyle = s.color; ctx.globalAlpha = 0.28; ctx.fill(f); ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width || 1.6;
      ctx.setLineDash(s.dash || []);
      ctx.lineJoin = 'round';
      ctx.stroke(path);
      ctx.setLineDash([]);
    }

    hoverLine(ctx, w, h, col, band) {
      const xx = this.px(this.hover, w);
      if (xx < M.left || xx > w - M.right) return;
      ctx.strokeStyle = col.fg;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(xx + 0.5, band ? 0 : 0); ctx.lineTo(xx + 0.5, h); ctx.stroke();
      ctx.globalAlpha = 1;
    }

    readout(p) {
      if (this.hover === null) { p.read.innerHTML = ''; return; }
      const fmt = p.def.format || ((v) => v.toFixed(1));
      p.read.innerHTML = p.def.series.map((s) => {
        const v = valueAt(s, this.hover);
        return v === null ? '' : '<span class="rd"><i style="background:' + s.color + '"></i>' + (s.label ? s.label + ' ' : '') + '<b>' + fmt(v) + '</b></span>';
      }).join('');
    }

    drawAxis(col) {
      const { ctx, w, h } = this.setup(this.axisCanvas);
      ctx.font = '11px system-ui, sans-serif';
      ctx.textBaseline = 'top';
      ctx.fillStyle = col.muted;
      ctx.strokeStyle = col.grid;
      const km = this.opts.lengthM ? this.opts.lengthM / 1000 : null;
      const [a, b] = this.view;
      const scale = km || 100;
      niceTicks(a * scale, b * scale, 8).forEach((v) => {
        const xx = this.px(v / scale, w);
        if (xx < M.left || xx > w - M.right) return;
        ctx.beginPath(); ctx.moveTo(xx + 0.5, 0); ctx.lineTo(xx + 0.5, 5); ctx.stroke();
        const t = km ? (+v.toFixed(2)) + ' km' : Math.round(v) + '%';
        ctx.fillText(t, xx - ctx.measureText(t).width / 2, 7);
      });
      if (this.hover !== null) {
        const xx = this.px(this.hover, w);
        if (xx >= M.left && xx <= w - M.right) {
          const t = km ? (this.hover * km).toFixed(2) + ' km' : (this.hover * 100).toFixed(1) + '%';
          ctx.fillStyle = col.fg;
          ctx.fillText(t, Math.min(w - M.right - 40, Math.max(M.left, xx - 20)), 7);
        }
      }
    }
  }

  window.LapCharts = LapCharts;
  window.chartValueAt = valueAt;
})();

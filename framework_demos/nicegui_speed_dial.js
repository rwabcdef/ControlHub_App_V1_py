// SpeedDial.tsx as a NiceGUI custom Vue component: an SVG knob that is dragged,
// scrolled or keyed in the browser (so it is smooth however slow the server
// link is), and emits "change" with whole numbers. mode: "edit", "readonly"
// (a meter: full colour, inert) or "disabled" (greyed).
const CX = 100, CY = 100, R = 80, START = 150, SWEEP = 240, GRAB = R - 30;
const polar = (r, deg) => { const a = (deg * Math.PI) / 180; return [CX + r * Math.cos(a), CY + r * Math.sin(a)]; };
const arc = (r, a0, a1) => {
  const [x0, y0] = polar(r, a0), [x1, y1] = polar(r, a1);
  return `M${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};
const fmtTick = (v) => (Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(1)}k` : `${Math.round(v)}`);

export default {
  template: `
    <svg ref="svg" viewBox="0 12 200 150" width="100%" height="100%" role="slider"
      :aria-valuemin="min" :aria-valuemax="max" :aria-valuenow="shown" :aria-disabled="mode === 'disabled'"
      :aria-readonly="mode === 'readonly'" :tabindex="live ? 0 : -1"
      :style="{ cursor: live ? 'pointer' : 'default', touchAction: 'none', outline: 'none', userSelect: 'none' }"
      @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @keydown="key" @wheel.prevent="wheel">
      <path :d="track" stroke="#262c35" stroke-width="6" fill="none" />
      <path :d="track" :stroke="ink" stroke-width="6" fill="none" pathLength="1000" :stroke-dasharray="frac * 1000 + ' 1000'" />
      <template v-for="t in ticks" :key="t.k">
        <line :x1="t.x0" :y1="t.y0" :x2="t.x1" :y2="t.y1" stroke="#9aa4af" :stroke-width="t.major ? 1.5 : 0.75" />
        <text v-if="t.label" :x="t.lx" :y="t.ly" font-size="8.5" fill="#9aa4af" text-anchor="middle" dominant-baseline="central">{{ t.label }}</text>
      </template>
      <g :transform="'rotate(' + angle + ' 100 100)'">
        <line x1="100" y1="100" :x2="100 + 80 - 6" y2="100" :stroke="ink" stroke-width="2.5" stroke-linecap="round" />
      </g>
      <circle v-if="shown !== null" :cx="knob[0]" :cy="knob[1]" r="7" fill="#161b22" :stroke="ink" stroke-width="2.5" />
      <circle cx="100" cy="100" r="5" fill="#161b22" :stroke="ink" stroke-width="2" />
      <text x="100" y="130" font-size="22" font-weight="600" text-anchor="middle"
        :fill="mode === 'disabled' ? '#5c6570' : '#e6edf3'" style="font-variant-numeric: tabular-nums">{{ shown ?? '—' }}</text>
      <text x="100" y="145" font-size="9" text-anchor="middle" fill="#9aa4af">{{ label }} ({{ unit }})</text>
    </svg>`,
  props: { value: Number, min: { type: Number, default: 0 }, max: Number, mode: String,
           color: String, label: String, unit: String },
  data() { return { local: null, dragging: false }; },
  computed: {
    live() { return this.mode === 'edit'; },
    ink() { return this.mode === 'disabled' ? '#4a525c' : this.color; },
    shown() { return this.local ?? this.value; },
    frac() {
      const v = this.shown; if (v === null || v === undefined) return 0;
      return Math.min(1, Math.max(0, (v - this.min) / (this.max - this.min)));
    },
    angle() { return START + this.frac * SWEEP; },
    knob() { return polar(R + 6, this.angle); },
    track() { return arc(R + 6, START, START + SWEEP); },
    ticks() {
      const out = [], n = 24;
      for (let i = 0; i <= n; i++) {
        const a = START + (SWEEP * i) / n, major = i % 4 === 0;
        const [x0, y0] = polar(R - (major ? 10 : 5), a), [x1, y1] = polar(R, a), [lx, ly] = polar(R - 20, a);
        out.push({ k: i, major, x0, y0, x1, y1, lx, ly,
                   label: major ? fmtTick(this.min + ((this.max - this.min) * i) / n) : null });
      }
      return out;
    },
  },
  watch: {
    // Hand back to the hub's value once it agrees, or when the dial stops taking input
    value(v) { if (!this.dragging && this.local !== null && v === this.local) this.local = null; },
    mode(m) { if (m !== 'edit') { this.dragging = false; this.local = null; } },
  },
  methods: {
    set(v) {
      const next = Math.min(this.max, Math.max(this.min, Math.round(v)));
      if (next === this.shown) return;
      this.local = next;
      this.$emit('change', next);
    },
    step(d) {
      const cur = this.shown ?? this.min;
      if ((cur > this.max && d > 0) || (cur < this.min && d < 0)) return;
      this.set(cur + d);
    },
    pointAt(e) {
      const r = this.$refs.svg.getBoundingClientRect();
      const s = Math.min(r.width / 200, r.height / 150);
      const x = (e.clientX - r.left - (r.width - 200 * s) / 2) / s;
      const y = (e.clientY - r.top - (r.height - 150 * s) / 2) / s + 12;
      const deg = (Math.atan2(y - CY, x - CX) * 180) / Math.PI;
      return { rel: (((deg - START) % 360) + 360) % 360, dist: Math.hypot(x - CX, y - CY) };
    },
    valueOf(rel) {
      const t = rel <= SWEEP ? rel / SWEEP : rel - SWEEP < 360 - rel ? 1 : 0;
      return this.min + t * (this.max - this.min);
    },
    down(e) {
      if (!this.live || e.button !== 0) return;
      this.$refs.svg.focus();
      const p = this.pointAt(e);
      if (p.dist < GRAB || p.rel > SWEEP) return;
      this.$refs.svg.setPointerCapture(e.pointerId);
      this.dragging = true;
      this.set(this.valueOf(p.rel));
    },
    move(e) { if (this.dragging) this.set(this.valueOf(this.pointAt(e).rel)); },
    up() {
      this.dragging = false;
      if (this.local !== null && this.value === this.local) this.local = null;
    },
    wheel(e) { if (this.live && e.deltaY !== 0) this.step(e.deltaY < 0 ? 1 : -1); },
    key(e) {
      if (!this.live) return;
      const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 10, PageDown: -10 }[e.key];
      if (d !== undefined) this.step(d);
      else if (e.key === 'Home') this.set(this.min);
      else if (e.key === 'End') this.set(this.max);
      else return;
      e.preventDefault();
    },
  },
};

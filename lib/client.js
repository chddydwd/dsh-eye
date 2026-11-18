
/**
 * dsh-eye —— 浏览器半侧：左侧栏「眼睛」入口 + 开关面板。
 *
 * 宿主的 __ModuleLoader__ 直接加载这份文件（整份是副作用脚本，不能有顶层 import/export；
 * react 从 factory 的 require 拿）。面板只做两件事：显示眼睛状态、开/关它。
 */
window.__ModuleLoader__.load({
  id: 'dsh-eye',
  factory: (require) => {
    const module = { exports: {} };
    const react = require('react');
    const h = react.createElement;

    const NAME = 'dsh-eye';
    const PANEL_ID = 'eye';
    const PREFIX = '/dsh-eye';
    // 桌面端窗口里 location.port 可能是空的：从注入的 <script src> 反推 DSH 端口（自检要用）
    const SELF_PORT = (() => {
      try {
        const s = document.currentScript;
        if (s && s.src) {
          const u = new URL(s.src);
          if (u.port) return u.port;
        }
      } catch (e) {}
      try { if (location.port) return location.port; } catch (e) {}
      return '';
    })();

    const CSS = [
      '.dsey-page{display:flex;flex-direction:column;gap:12px;height:100%;min-height:0;padding:14px 16px;overflow:auto;font-size:12.5px;line-height:1.55;color:inherit}',
      '.dsey-head{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:10px;background:rgba(10,16,24,.42);border:1px solid rgba(255,255,255,.05)}',
      '.dsey-title{font-size:14px;font-weight:600}',
      '.dsey-badge{font-size:11px;padding:1px 9px;border-radius:999px;border:1px solid currentColor;opacity:.95}',
      '.dsey-badge.on{color:#35c07a}',
      '.dsey-badge.off{color:#ff8a7a;opacity:.8}',
      '.dsey-btn{margin-left:auto;font:inherit;font-size:12px;padding:4px 12px;border-radius:8px;cursor:pointer;background:rgba(10,16,24,.44);color:inherit;border:1px solid rgba(255,255,255,.09)}',
      '.dsey-btn:hover{background:rgba(38,54,72,.72);border-color:rgba(255,255,255,.18)}',
      '.dsey-btn:disabled{opacity:.5;cursor:default}',
    '.dsey-btn.dsey-on{background:rgba(58,111,156,.55);border-color:#3a6f9c;color:#dff1ff}',
      '.dsey-meta{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;opacity:.82;padding:6px 11px;border-radius:9px;background:rgba(10,16,24,.34)}',
      '.dsey-note{font-size:11.5px;opacity:.62;padding:0 4px}',
      '.dsey-err{font-size:12px;color:#ff6b60}',
      '.dsey-sec{margin-top:4px;padding:10px 12px;border-radius:10px;background:rgba(10,16,24,.42);border:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:8px}',
      '.dsey-sec-t{font-size:12px;font-weight:600;opacity:.9}',
      '.dsey-pre{margin:0;padding:8px 10px;border-radius:8px;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.07);font-family:ui-monospace,Consolas,monospace;font-size:11.5px;line-height:1.5;white-space:pre-wrap;word-break:break-all;max-height:240px;overflow:auto;opacity:.92}',
      '.dsey-meta .dsey-btn,.dsey-alert .dsey-btn{margin-left:0!important;flex:0 0 auto;width:auto;min-width:0}',
      '.dsey-alert{gap:8px;flex-wrap:wrap}',
      '.dsey-meta>.dsey-note{flex:1 1 220px;min-width:0}',
      '.dsey-row{display:flex;align-items:center;gap:10px;font-size:11.5px}',
      '.dsey-row>span:first-child{width:88px;opacity:.72;flex:none}',
      '.dsey-row input[type=range]{flex:1;min-width:0;accent-color:#4aa8ff}',
      '.dsey-num{width:62px;font:inherit;font-size:11.5px;padding:2px 6px;border-radius:6px;background:rgba(20,30,42,.9);color:inherit;border:1px solid rgba(255,255,255,.14);text-align:right}',
      '.dsey-foot{display:flex;align-items:center;gap:8px;font-size:11px;opacity:.75;flex-wrap:wrap}',
      '.dsey-foot .dsey-btn{margin-left:0}',
      '.dsey-evt{display:flex;gap:10px;font-size:11px;opacity:.86;white-space:nowrap;overflow:hidden}',
      '.dsey-evt-t{opacity:.72;flex:none}',
      '.dsey-evt-s{flex:none;opacity:.9}',
      '.dsey-evt-w{opacity:.6;overflow:hidden;text-overflow:ellipsis}',
      '.dsey-sec-in{background:transparent;border:0;padding:0;margin-top:0}',
      '.dsey-sec-tg{cursor:pointer;user-select:none}',
      '.dsey-sub{font-size:11px;font-weight:600;opacity:.78;margin-top:10px}',
      '.dsey-item{display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-top:1px solid rgba(255,255,255,.055)}',
      '.dsey-item:first-of-type{border-top:0;padding-top:2px}',
      '.dsey-item-l{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px}',
      '.dsey-item-t{font-size:12px;font-weight:600;opacity:.92}',
      '.dsey-item-n{font-size:11px;opacity:.55;line-height:1.45}',
      '.dsey-item-c{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;flex:0 0 auto;max-width:58%}',
      '.dsey-item-c .dsey-btn{margin-left:0!important}',
      '.dsey-hint{font-size:11px;opacity:.55;line-height:1.5}',
      '.dsey-tip{font-size:11px;opacity:.5;padding:2px 4px;line-height:1.5}',
      '.dsey-help{font-size:11.5px;line-height:1.8;opacity:.82;margin-top:7px}',
      '.dsey-help>div{margin-bottom:3px}',
      '.dsey-live{width:100%;max-width:560px;border-radius:8px;border:1px solid rgba(255,255,255,.08);display:block;background:#0a1018}',
      '.dsey-live+.dsey-note{padding:0}',
      '.dsey-live-t{display:flex;align-items:center;gap:8px;font-size:11.5px;opacity:.7}',
    ].join('\n');

    function injectCss() {
      try {
        if (document.getElementById('dsh-eye-css')) return;
        const s = document.createElement('style');
        s.id = 'dsh-eye-css';
        s.textContent = CSS;
        document.head.appendChild(s);
      } catch (e) {}
    }

    async function api(path) {
      const r = await fetch(PREFIX + path, { headers: { accept: 'application/json' } });
      return r.json();
    }

    function EyeIcon() {
      return h(
        'svg',
        {
          'aria-hidden': true, width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
          stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round',
          style: { display: 'block', margin: 'auto' },
        },
        h('path', { d: 'M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z' }),
        h('circle', { cx: 12, cy: 12, r: 2.6 }),
      );
    }

    const EYE = 'http://127.0.0.1:13201';

    const KNOBS = [
      { k: 'near_span', label: '近层时长', unit: '秒', min: 5, max: 120, step: 5 },
      { k: 'near_fps', label: '近层帧率', unit: 'fps', min: 5, max: 30, step: 1 },
      { k: 'idle_fps', label: '静止时帧率', unit: 'fps', min: 1, max: 15, step: 1 },
      { k: 'far_step', label: '远层间隔', unit: '秒', min: 0.5, max: 10, step: 0.5 },
      { k: 'far_sec', label: '远层时长', unit: '秒', min: 300, max: 7200, step: 300 },
      { k: 'quality', label: '画质', unit: '', min: 50, max: 95, step: 1 },
    ];

    const PRESETS = [
      {
        k: 'low',
        label: '低',
        note: '老笔记本也能跑：近层 15 秒 / 8fps、静止 3fps、远层 5 秒一张只留 15 分钟、画质 60。省一半资源，代价是动作过程变粗、小字要凑近看。',
        v: { near_span: 15, near_fps: 8, idle_fps: 3, far_step: 5, far_sec: 900, quality: 60 },
      },
      {
        k: 'mid',
        label: '中',
        note: '默认均衡：一般机器都跑得动，刚发生的动作看得清，近层留 30 秒、远层留 1 小时。',
        v: { near_span: 30, near_fps: 20, idle_fps: 5, far_step: 2, far_sec: 3600, quality: 82 },
      },
      {
        k: 'high',
        label: '高',
        note: '好机器用：近层 45 秒 / 25fps、静止 6fps、远层 1 秒一张、画质 90。动作更连贯、字更清楚，CPU 和内存也更高。',
        v: { near_span: 45, near_fps: 25, idle_fps: 6, far_step: 1, far_sec: 3600, quality: 90 },
      },
    ];

    function Settings({ auto }) {
      const [cfg, setCfg] = react.useState(null);
      const [draft, setDraft] = react.useState(null);
      const [msg, setMsg] = react.useState('');
      const [busy, setBusy] = react.useState(false);

      const load = react.useCallback(async () => {
        try {
          const r = await fetch(EYE + '/config');
          const c = await r.json();
          setCfg(c); setDraft(c);
        } catch (e) { setMsg('读不到眼睛参数：' + String((e && e.message) || e)); }
      }, []);
      react.useEffect(() => { load(); }, [load]);

      const set = (k, v) => setDraft((d) => ({ ...d, [k]: Number(v) }));

      const save = async (override) => {
        const d0 = override || draft;
        if (!d0) return;
        setBusy(true); setMsg('');
        try {
          const qs = KNOBS.map((kn) => kn.k + '=' + encodeURIComponent(d0[kn.k])).join('&');
          const r = await fetch(EYE + '/config?' + qs);
          const c = await r.json();
          setCfg(c); setDraft(c);
          setMsg('已生效 · 预计占用 ' + c.est_mem_mb + ' MB');
        } catch (e) { setMsg('保存失败：' + String((e && e.message) || e)); }
        setBusy(false);
      };

      if (!draft) return h('div', { className: 'dsey-sec' }, h('div', { className: 'dsey-sec-t' }, '眼睛参数'), h('div', { className: 'dsey-note' }, msg || '读取中…'));

      const preset = PRESETS.filter((p) => KNOBS.every((kn) => Number(p.v[kn.k]) === Number(draft[kn.k])))[0] || null;
      const usePreset = async (p) => {
        const d0 = { ...draft, ...p.v };
        setDraft(d0);
        await save(d0);
      };
      const autoOn = !!(auto && auto.on);
      const setAuto = async (v) => {
        setBusy(true);
        try {
          await fetch(EYE + '/auto?on=' + (v ? 1 : 0));
          setMsg(v ? '自动性能档已开：吃力就自己退档，余量够了再升回来。' : '自动性能档已关：完全按你设的档跑。');
        } catch (e) { setMsg('切换失败：' + String((e && e.message) || e)); }
        setBusy(false);
      };

      return h(
        'div',
        { className: 'dsey-sec dsey-sec-in' },
        h('div', { className: 'dsey-sec-t' }, '眼睛参数'),
        h(
          'div',
          { className: 'dsey-meta dsey-alert' },
          h('span', null, '性能档'),
          PRESETS.map((p) =>
            h(
              'button',
              {
                key: p.k,
                className: 'dsey-btn' + (preset && preset.k === p.k ? ' dsey-on' : ''),
                onClick: () => usePreset(p),
                disabled: busy,
              },
              p.label,
            ),
          ),
          h('span', { className: 'dsey-note' }, preset ? preset.note : '自定义：你改过滑块，不假装还是预设；想回档就点低/中/高。'),
        ),
        h(
          'div',
          { className: 'dsey-meta dsey-alert' },
          h('span', null, '自动性能档'),
          h('button', { className: 'dsey-btn' + (autoOn ? ' dsey-on' : ''), onClick: () => setAuto(true), disabled: busy }, '开'),
          h('button', { className: 'dsey-btn' + (autoOn ? '' : ' dsey-on'), onClick: () => setAuto(false), disabled: busy }, '关'),
          h('span', { className: 'dsey-note' }, autoOn
            ? ('开着：现在封顶 ' + ((auto && auto.cap) || '—') + ' fps · 实测单帧 ' + ((auto && auto.avg_ms) || '—') + ' ms · ' + ((auto && auto.note) || '自动'))
            : '关着：完全按你设的帧率跑，吃力就掉帧。'),
        ),
        KNOBS.map((kn) =>
          h(
            'div',
            { className: 'dsey-row', key: kn.k },
            h('span', null, kn.label),
            h('input', {
              type: 'range', min: kn.min, max: kn.max, step: kn.step,
              value: draft[kn.k], onChange: (e) => set(kn.k, e.target.value),
            }),
            h('span', { className: 'dsey-num' }, String(draft[kn.k]) + (kn.unit ? ' ' + kn.unit : '')),
          ),
        ),
        h(
          'div',
          { className: 'dsey-foot' },
          h('button', { className: 'dsey-btn', onClick: () => save(), disabled: busy }, busy ? '…' : '保存'),
          h('button', { className: 'dsey-btn', onClick: () => { if (cfg && cfg.defaults) setDraft({ ...cfg.defaults }); } }, '恢复默认'),
          h('span', null, '现在：近 ' + (cfg ? cfg.near_frames : '-') + ' 张 / 远 ' + (cfg ? cfg.far_frames : '-') + ' 张 · 每帧 ' + (cfg ? cfg.frame_kb : '-') + 'KB · 约 ' + (cfg ? cfg.est_mem_mb : '-') + ' MB'),
        ),
        msg ? h('div', { className: 'dsey-note' }, msg) : null,
      );
    }

    const VIEWS = [
      { k: 'live', label: '实时', note: '环里最新那一帧。把「画质」调低，这里也会跟着糊——就是你给模型看的东西。' },
      { k: 'sheet', label: '余光拼图', note: '近层时长覆盖的那一段压成格子，先看哪一块在动；模型看动作过程用的就是它。' },
      { k: 'echo', label: '动作回声', note: '最近一次点击的前后几帧。点过屏幕才有，用来看这一下点中没。' },
      { k: 'focus', label: '聚焦', note: '按光标位置裁一块 1:1 原像素，小字能读清——模型「凑近看」就是这个视角。' },
    ];

    function Live({ mode, onPick, clicks }) {
      const [ts, setTs] = react.useState(0);
      const [view, setView] = react.useState(() => {
        try { return localStorage.getItem('dsh-eye-view') || 'live'; } catch (e) { return 'live'; }
      });
      const [cfg, setCfg] = react.useState(null);
      react.useEffect(() => {
        if (mode === 'off') return undefined;
        let stop = false;
        setTs(Date.now());
        const every = view === 'live' ? 1500 : 3000;
        const t = setInterval(() => { if (!stop) setTs(Date.now()); }, every);
        return () => { stop = true; clearInterval(t); };
      }, [mode, view]);
      react.useEffect(() => {
        let stop = false;
        fetch(EYE + '/config')
          .then((r) => r.json())
          .then((c) => { if (!stop) setCfg(c); })
          .catch(() => {});
        return () => { stop = true; };
      }, []);
      const pick = (v) => {
        setView(v);
        try { localStorage.setItem('dsh-eye-view', v); } catch (e) {}
      };
      const big = mode === 'big';
      const q = cfg && cfg.quality ? cfg.quality : 68;
      const span = cfg && cfg.near_span ? cfg.near_span : 30;
      const cur = VIEWS.filter((v) => v.k === view)[0] || VIEWS[0];
      const noEcho = view === 'echo' && !clicks;
      const src = noEcho
        ? ''
        : EYE + (view === 'live'
            ? '/live?w=' + (big ? 520 : 260) + '&q=' + q + '&t=' + ts
            : view === 'sheet'
              ? '/window?span=' + span + '&n=100&cols=10&t=' + ts
              : view === 'echo'
                ? '/echo?before=1&after=1.2&t=' + ts
                : '/fovea_at_cursor?fw=700&fh=393&t=' + ts);
      return h(
        'div',
        { style: { display: 'flex', flexDirection: 'column', gap: '8px' } },
        h(
          'div',
          { className: 'dsey-meta dsey-alert' },
          h('span', null, '视角'),
          VIEWS.map((v) =>
            h(
              'button',
              { key: v.k, className: 'dsey-btn' + (view === v.k ? ' dsey-on' : ''), onClick: () => pick(v.k) },
              v.label,
            ),
          ),
          h('span', { className: 'dsey-note' }, cur.note),
        ),
        h(
          'div',
          { className: 'dsey-meta dsey-alert' },
          h('span', null, '大小'),
          h('button', { className: 'dsey-btn' + (mode === 'off' ? ' dsey-on' : ''), onClick: () => onPick('off') }, '关'),
          h('button', { className: 'dsey-btn' + (mode === 'small' ? ' dsey-on' : ''), onClick: () => onPick('small') }, '小图'),
          h('button', { className: 'dsey-btn' + (mode === 'big' ? ' dsey-on' : ''), onClick: () => onPick('big') }, '大图'),
          h('span', { className: 'dsey-note' }, mode === 'off' ? '关掉不占地方，采集照常' : cfg ? '画质 ' + q + ' · 近层 ' + span + ' 秒（参数一改，这里跟着变）' : '读参数中…'),
        ),
        mode === 'off' || !ts || !src
          ? noEcho
            ? h('div', { className: 'dsey-note' }, '还没点过屏幕——点一下再回来看。')
            : null
          : h('img', {
              className: 'dsey-live',
              style: { maxWidth: (big ? 560 : 240) + 'px' },
              alt: '眼睛画面',
              src: src,
            }),
      );
    }

    const EV_KIND = { click: '点击', scroll: '滚动', window: '换窗口' };
    function agoText(sec) {
      if (sec == null) return '';
      if (sec < 1) return '刚刚';
      if (sec < 60) return Math.round(sec) + '秒前';
      if (sec < 3600) return Math.round(sec / 60) + '分钟前';
      return Math.round(sec / 3600) + '小时前';
    }

    function Events() {
      const [ev, setEv] = react.useState([]);
      react.useEffect(() => {
        let stop = false;
        const load = () => {
          fetch(EYE + '/events?n=5')
            .then((r) => r.json())
            .then((d) => { if (!stop) setEv((d && d.events) || []); })
            .catch(() => {});
        };
        load();
        const t = setInterval(load, 3000);
        return () => { stop = true; clearInterval(t); };
      }, []);
      const line = ev.length
        ? ev.map((e) => agoText(e.ago) + ' ' + (EV_KIND[e.kind] || e.kind) + (e.title ? '「' + String(e.title).slice(0, 16) + '」' : '')).join(' · ')
        : '还没有事件——点一下鼠标、换个窗口就会记一笔（滚动要开鼠标钩子）。';
      return h(
        'div',
        { className: 'dsey-meta' },
        h('span', null, '事件'),
        h('span', { className: 'dsey-note' }, line),
      );
    }



    function Item(label, note, kids) {
      return h(
        'div',
        { style: { display: 'flex', alignItems: 'flex-start', gap: '10px', padding: '8px 0', borderTop: '1px solid rgba(255,255,255,.06)' } },
        h(
          'div',
          { style: { flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '2px' } },
          h('span', { style: { fontSize: '12px', fontWeight: 600, opacity: 0.92 } }, label),
          note ? h('span', { style: { fontSize: '11.5px', opacity: 0.68, lineHeight: 1.45 } }, note) : null,
        ),
        h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '6px', justifyContent: 'flex-end', flex: '0 0 auto', maxWidth: '58%' } }, kids),
      );
    }

    function Btn(text, active, onClick, disabled) {
      return h('button', { key: text, className: 'dsey-btn' + (active ? ' dsey-on' : ''), onClick: onClick, disabled: disabled }, text);
    }

    function Panel() {
      const [st, setSt] = react.useState({ alive: false, state: null, watch: null, err: '' });
      const [busy, setBusy] = react.useState(false);
      const [help, setHelp] = react.useState(false);
      const [open, setOpen] = react.useState({ param: false, tool: false, log: false });
      const [doc, setDoc] = react.useState({ busy: false, text: '', ok: null });
      const runDoctor = async () => {
        setDoc({ busy: true, text: '', ok: null });
        try {
          const port = SELF_PORT || (typeof location !== 'undefined' && location.port) || '';
          const r = await fetch(PREFIX + '/doctor?port=' + encodeURIComponent(port)).then((x) => x.json());
          setDoc({ busy: false, text: String(r.text || r.error || ''), ok: r.ok });
        } catch (e) {
          setDoc({ busy: false, text: '自检没跑起来：' + String((e && e.message) || e), ok: false });
        }
      };

      const refresh = react.useCallback(async () => {
        try { setSt(await api('/state')); } catch (e) { setSt((s) => ({ ...s, err: String((e && e.message) || e) })); }
      }, []);

      react.useEffect(() => {
        let stop = false;
        refresh();
        const t = setInterval(() => { if (!stop) refresh(); }, 2000);
        return () => { stop = true; clearInterval(t); };
      }, [refresh]);

      const toggle = async () => {
        setBusy(true);
        try { await api('/toggle?on=' + (st.alive ? '0' : '1')); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const w = st.watch || {};
      const toggleWatch = async () => {
        setBusy(true);
        try { await api('/watch?on=' + (w.on ? '0' : '1')); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const toggleAuto = async () => {
        setBusy(true);
        try { await api('/autostart?on=' + (st.autostart ? '0' : '1')); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const toggleMode = async () => {
        setBusy(true);
        const next = w.mode === 'wake' ? 'panel' : w.mode === 'panel' ? 'toast' : 'wake';
        try { await api('/watch?mode=' + next); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const setAlert = async (a) => {
        setBusy(true);
        try { await api('/watch?alert=' + a); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const openChatWin = async () => {
        setBusy(true);
        try { await api('/chat?open=1'); await refresh(); } catch (e) {}
        setBusy(false);
      };

      const s = st.state || {};
      const rg = s.region || null;
      const boxed = !!(rg && rg.w >= 60 && rg.h >= 60);
      const msens = (s.mask && s.mask.sens) || null;
      const sensOn = !!(msens && msens.on);
      const mk = s.mask || null;
      const maskOn = !!(mk && mk.on && mk.count > 0);
      const hk = s.hooks || null;
      const hkOn = !!(hk && hk.on);
      const secOpen = open || {};
      const toggleSec = (k) => setOpen((o) => { const n = Object.assign({}, o || {}); n[k] = !n[k]; return n; });
      const SecT = (title, k) => h('div', { className: 'dsey-sec-t dsey-sec-tg', onClick: () => toggleSec(k) }, title + (secOpen[k] ? '   ▾' : '   ▸'));

      const statusRow = st.alive
        ? h(
            'div',
            { className: 'dsey-meta' },
            h('span', null, (s.frames || 0) + ' 帧'),
            h('span', null, (s.fps || 0) + ' fps'),
            h('span', null, '环 ' + (s.span_sec || 0) + ' 秒'),
            h('span', null, '光标 ' + (s.cursor ? s.cursor.join(',') : '-')),
            h('span', null, '点击 ' + (s.clicks || 0) + ' 次'),
          )
        : null;

      const nowSec = st.alive
        ? h(
            'div',
            { className: 'dsey-sec' },
            h('div', { className: 'dsey-sec-t' }, '现在眼睛看到的'),
            h(Live, {
              mode: st.live === 'off' || st.live === 'big' ? st.live : 'small',
              clicks: s.clicks || 0,
              onPick: async (v) => {
                try { await api('/livepref?mode=' + v); } catch (e) {}
                await refresh();
              },
            }),
            h(Events),
          )
        : null;

      const commonSec = st.alive
        ? h(
            'div',
            { className: 'dsey-sec' },
            h('div', { className: 'dsey-sec-t' }, '常用开关'),
            Item(
              '录哪里',
              boxed ? '只录这一块（' + rg.w + '×' + rg.h + '），其余不抓' : '整屏都录，最省事',
              [
                Btn('整屏', !boxed, async () => { try { await fetch(EYE + '/region?off=1') } catch (e) {} setTimeout(refresh, 400) }, busy),
                Btn('框一块', boxed, async () => { try { await fetch(EYE + '/region/pick') } catch (e) {} setTimeout(refresh, 2500) }, busy),
              ],
            ),
            Item(
              '敏感窗口自动挡',
              sensOn ? (msens.hit ? '正在挡「' + String(msens.title || '').slice(0, 12) + '」' : '银行、支付、密码这类窗口自动糊掉') : '关着，不自动挡',
              [Btn('关', !sensOn, async () => { try { await fetch(EYE + '/sensitive?on=0') } catch (e) {} setTimeout(refresh, 400) }, busy),
               Btn('开', sensOn, async () => { try { await fetch(EYE + '/sensitive?on=1') } catch (e) {} setTimeout(refresh, 400) }, busy)],
            ),
            Item(
              '隐私打码',
              maskOn ? '框了 ' + mk.count + ' 块：图里糊掉、读字也跳过' : '没框；密码框、聊天区可以框一下',
              [
                Btn('框一块', false, async () => { try { await fetch(EYE + '/mask/pick') } catch (e) {} }, busy),
                Btn('清除', false, async () => { try { await fetch(EYE + '/mask?clear=1') } catch (e) {} setTimeout(refresh, 400) }, busy),
                Btn('开', maskOn, async () => { try { await fetch(EYE + '/mask?on=1') } catch (e) {} setTimeout(refresh, 400) }, busy),
                Btn('关', !maskOn, async () => { try { await fetch(EYE + '/mask?on=0') } catch (e) {} setTimeout(refresh, 400) }, busy),
              ],
            ),
            Item(
              '鼠标钩子',
              hkOn ? '开着：点下去那一刻就有帧，连点不漏' : hk && hk.want && hk.err ? '想开但失败，已退回轮询' : '关着：靠轮询，快速连点会漏',
              [Btn('关', !hkOn, async () => { try { await fetch(EYE + '/hooks?on=0') } catch (e) {} setTimeout(refresh, 500) }, busy),
               Btn('开', hkOn, async () => { try { await fetch(EYE + '/hooks?on=1') } catch (e) {} setTimeout(refresh, 900) }, busy)],
            ),
            Item(
              '大变化时',
              w.on ? '叫我：' + (w.mode === 'wake' ? '投一条提示给我' : w.mode === 'toast' ? '屏幕上闪一条' : '只记在面板') : '不叫，只记录',
              [Btn('别看了', !w.on, toggleWatch, busy), Btn('盯着点', w.on, toggleWatch, busy)],
            ),
            Item(
              '怎么叫',
              '现在：' + (w.mode === 'wake' ? '投聊天' : w.mode === 'toast' ? '闪屏幕' : '挂面板') + '。闪屏幕不打断你，投聊天最显眼。',
              [Btn('挂面板', w.mode === 'panel', async () => { try { await api('/watch?mode=panel'); } catch (e) {} await refresh(); }, busy),
               Btn('闪屏幕', w.mode === 'toast', async () => { try { await api('/watch?mode=toast'); } catch (e) {} await refresh(); }, busy),
               Btn('投聊天', w.mode === 'wake', async () => { try { await api('/watch?mode=wake'); } catch (e) {} await refresh(); }, busy)],
            ),
            Item(
              '灵敏度',
              w.alert === 'quiet' ? '少打扰：只记换窗口、整屏大改' : w.alert === 'sensitive' ? '别漏：稍微一动就记' : '平衡：换窗口和整屏大改都记',
              [Btn('少打扰', w.alert === 'quiet', () => setAlert('quiet'), busy),
               Btn('平衡', w.alert !== 'quiet' && w.alert !== 'sensitive', () => setAlert('normal'), busy),
               Btn('别漏', w.alert === 'sensitive', () => setAlert('sensitive'), busy)],
            ),
            Item(
              'DSH 一开就自动录',
              st.autostart ? '自动：打开 DSH 眼睛跟着开' : '手动：每次自己点「打开」',
              [Btn('手动', !st.autostart, toggleAuto, busy), Btn('自动', st.autostart, toggleAuto, busy)],
            ),
            h('div', { className: 'dsey-tip' },
              '屏幕 ' + (s.monitor ? s.monitor.width + 'x' + s.monitor.height : '-')
              + (s.refresh ? ' @' + s.refresh + 'Hz' : '')
              + ' / 缩放 ' + Math.round((s.dpi || 1) * 100) + '%'),
          )
        : null;

      const paramSec = h(
        'div',
        { className: 'dsey-sec' },
        SecT('性能与参数', 'param'),
        secOpen.param
          ? h('div', null, h(Settings, { auto: s.auto || null }))
          : h('div', { style: { fontSize: '11px', opacity: 0.55, lineHeight: 1.5 } }, '低 / 中 / 高 一键换参数；帧率、画质、留多久都在里面。不懂就别动，默认够用。'),
      );

      const toolSec = h(
        'div',
        { className: 'dsey-sec' },
        SecT('工具与说明', 'tool'),
        secOpen.tool
          ? h(
              'div',
              null,
              h('div', { style: { fontSize: '11px', fontWeight: 600, opacity: 0.78, marginTop: '10px' } }, '对话框'),
              h('div', { className: 'dsey-note' }, '开个小窗，你打字我就在旁边回，不用等 QQ。'),
              h('div', { className: 'dsey-foot' },
                h('button', { className: 'dsey-btn', onClick: openChatWin, disabled: busy }, st.chat && st.chat.open ? '窗口开着（再点一下）' : '打开对话框'),
                st.chat && st.chat.lastErr ? h('span', { className: 'dsey-err' }, st.chat.lastErr) : null),
              h('div', { className: 'dsey-sub' }, '自检'),
              h('div', { className: 'dsey-note' }, '哪里不对劲先点它：采集、活动、参数、进程各看一眼。'),
              h('div', { className: 'dsey-foot' },
                h('button', { className: 'dsey-btn', onClick: runDoctor, disabled: doc.busy }, doc.busy ? '检查中…' : '跑一次自检'),
                doc.text ? h('span', { className: 'dsey-note' }, doc.ok === false ? '有毛病' : '看着正常') : null),
              doc.text ? h('pre', { className: 'dsey-pre' }, doc.text) : null,
              h('div', { className: 'dsey-sub' }, '怎么用'),
              h(
                'div',
                { className: 'dsey-help' },
                h('div', null, '1. 点右上角「打开」就开录，两秒后出现帧数；「关掉」是真把采集进程杀掉。'),
                h('div', null, '2. 平时不用管，屏幕真大变时按你选的方式提醒（挂面板 / 闪屏幕 / 投聊天）。'),
                h('div', null, '3. 想让鲸鲸看刚才：直接说「看看刚才」「刚才那下点中没」，它会自己取图。'),
                h('div', null, '4. 只录一个窗口或一段视频：点「框一块」，屏幕暗下来拖一个框，松手生效；点「整屏」恢复。'),
                h('div', null, '5. 怕露密码 / 聊天：点「隐私打码」里的「框一块」，把那块框住，之后所有图里都是马赛克，读字也跳过。'),
                h('div', null, '6. 银行、支付这类窗口默认会被自动糊掉（认窗口标题）；标题没写明白的，用第 5 条手动框。'),
                h('div', null, '7. 「鼠标钩子」开着点得更准，但个别安全软件会提示；介意就关，功能不受影响。'),
                h('div', null, '8. 「性能与参数」：低 / 中 / 高 一键换；自动性能档默认开，吃力自己退档，不用懂参数。'),
                h('div', null, '9. 换了显示器 / 分辨率 / 缩放不用改设置，自动识别；多屏暂时只录主屏。'),
                h('div', null, '10. 屏幕不对劲就点「自检」，把结果发给鲸鲸。'),
              ),
            )
          : h('div', { className: 'dsey-hint' }, '自检、对话框、怎么用，都收在这里。'),
      );

      const logSec = h(
        'div',
        { className: 'dsey-sec' },
        SecT('最近大变化' + (w.events && w.events.length ? '（' + w.events.length + '）' : ''), 'log'),
        secOpen.log
          ? (w.events && w.events.length
              ? w.events.slice().reverse().slice(0, 12).map((ev, i) =>
                  h('div', { className: 'dsey-evt', key: i },
                    h('span', { className: 'dsey-evt-t' }, new Date(ev.t).toLocaleTimeString('zh-CN', { hour12: false })),
                    h('span', { className: 'dsey-evt-s' }, ev.kind === 'window' ? '换窗口' : '画面大改'),
                    h('span', { className: 'dsey-evt-w' }, ev.title ? '「' + ev.title + '」' : '')))
              : h('div', { className: 'dsey-note' }, '还没记到大幅变化。'))
          : h('div', { className: 'dsey-hint' }, w.events && w.events.length ? '最近记了 ' + w.events.length + ' 次，点开看' : '还没记到大幅变化。'),
      );

      return h(
        'div',
        { className: 'dsey-page' },
        h(
          'div',
          { className: 'dsey-head' },
          h('span', { className: 'dsey-title' }, '眼睛'),
          h('span', { className: 'dsey-badge ' + (st.alive ? 'on' : 'off') }, st.alive ? '在录' : '关了'),
          h('button', { className: 'dsey-btn', onClick: toggle, disabled: busy }, busy ? '…' : st.alive ? '关掉' : '打开'),
        ),
        statusRow,
        nowSec,
        commonSec,
        paramSec,
        toolSec,
        logSec,
        h('div', { style: { fontSize: '11px', opacity: 0.5, padding: '2px 4px', lineHeight: 1.5 } }, '只留内存、不落盘；关掉＝真把采集进程杀掉。'),
        st.err ? h('div', { className: 'dsey-err' }, '出错：' + st.err) : null,
      );
    }


    const inject = ['slots'];

    function apply(ctx) {
      try {
        injectCss();
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: PANEL_ID }, Panel));
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: PANEL_ID, order: 61, label: () => '眼睛' }, EyeIcon),
        );
      } catch (e) {}
    }

    module.exports = { name: NAME, inject, apply, Panel, EyeIcon, PANEL_ID };
    return module.exports;
  },
});

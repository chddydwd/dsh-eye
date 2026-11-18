
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
      { k: 'idle_fps', label: '闲着时帧率', unit: 'fps', min: 1, max: 15, step: 1 },
      { k: 'far_step', label: '远层间隔', unit: '秒', min: 0.5, max: 10, step: 0.5 },
      { k: 'far_sec', label: '远层时长', unit: '秒', min: 300, max: 7200, step: 300 },
      { k: 'quality', label: '画质', unit: '', min: 50, max: 95, step: 1 },
    ];

    const PRESETS = [
      {
        k: 'low',
        label: '低',
        note: '老笔记本也能跑：近层 15 秒 / 8fps、闲着 1fps、远层 5 秒一张只留 15 分钟、画质 60。省一半资源，代价是动作过程变粗、小字要凑近看。',
        v: { near_span: 15, near_fps: 8, idle_fps: 1, far_step: 5, far_sec: 900, quality: 60 },
      },
      {
        k: 'mid',
        label: '中',
        note: '默认均衡：一般机器都跑得动，刚发生的动作看得清，近层留 30 秒、远层留 1 小时。',
        v: { near_span: 30, near_fps: 20, idle_fps: 2, far_step: 2, far_sec: 3600, quality: 82 },
      },
      {
        k: 'high',
        label: '高',
        note: '好机器用：近层 45 秒 / 25fps、闲置 3fps、远层 1 秒一张、画质 90。动作更连贯、字更清楚，CPU 和内存也更高。',
        v: { near_span: 45, near_fps: 25, idle_fps: 3, far_step: 1, far_sec: 3600, quality: 90 },
      },
    ];

    function Settings() {
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

      return h(
        'div',
        { className: 'dsey-sec' },
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
        { className: 'dsey-sec' },
        h('div', { className: 'dsey-sec-t' }, '现在眼睛看到的'),
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

    function Panel() {
      const [st, setSt] = react.useState({ alive: false, state: null, watch: null, err: '' });
      const [busy, setBusy] = react.useState(false);
      const [help, setHelp] = react.useState(false);

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
        st.alive
          ? h(
              'div',
              { className: 'dsey-meta' },
              h('span', null, (s.frames || 0) + ' 帧'),
              h('span', null, (s.fps || 0) + ' fps'),
              h('span', null, '环 ' + (s.span_sec || 0) + ' 秒'),
              h('span', null, '光标 ' + (s.cursor ? s.cursor.join(',') : '-')),
              h('span', null, '点击 ' + (s.clicks || 0) + ' 次'),
            )
          : null,
        st.alive
          ? h(
              'div',
              { className: 'dsey-meta' },
              h('span', null, '叫醒 ' + (w.on ? '开' : '关')),
              h('span', null, '阈值 ' + (w.threshold != null ? w.threshold : '-')),
              h('span', null, '上一拍 ' + (w.lastScore || 0)),
              h('span', null, '记录 ' + (w.mode === 'wake' ? '投聊天' : w.mode === 'toast' ? '闪屏幕' : '挂面板')),
              h('button', { className: 'dsey-btn', onClick: toggleWatch, disabled: busy }, w.on ? '别看了' : '盯着点'),
              h('button', { className: 'dsey-btn', onClick: toggleMode, disabled: busy }, w.mode === 'wake' ? '改成挂面板' : w.mode === 'panel' ? '改成闪屏幕' : '改成叫醒我'),
              h('span', null, '启动 ' + (st.autostart ? '自动' : '手动')),
              h('button', { className: 'dsey-btn', onClick: toggleAuto, disabled: busy }, st.autostart ? '改成手动' : '改成自动'),
            )
          : null,
        st.alive
          ? h(
              'div',
              { className: 'dsey-meta dsey-alert' },
              h('span', null, '灵敏度 ' + (w.alert === 'quiet' ? '少打扰' : w.alert === 'sensitive' ? '别漏' : '平衡')),
              h('button', { className: 'dsey-btn' + (w.alert === 'quiet' ? ' dsey-on' : ''), onClick: () => setAlert('quiet'), disabled: busy }, '少打扰'),
              h('button', { className: 'dsey-btn' + (w.alert !== 'quiet' && w.alert !== 'sensitive' ? ' dsey-on' : ''), onClick: () => setAlert('normal'), disabled: busy }, '平衡'),
              h('button', { className: 'dsey-btn' + (w.alert === 'sensitive' ? ' dsey-on' : ''), onClick: () => setAlert('sensitive'), disabled: busy }, '别漏'),
              h('span', { className: 'dsey-note' }, w.alert === 'quiet' ? '只记很确定的（换窗口/整屏大改），几乎不吵' : w.alert === 'sensitive' ? '稍微一动就记，适合盯流程/抓细节' : '默认：换窗口和整屏大改都记，中间的吞掉'),
            )
          : null,
        st.alive
          ? h(Live, {
              mode: st.live === 'off' || st.live === 'big' ? st.live : 'small',
              clicks: (st.state && st.state.clicks) || 0,
              onPick: async (v) => {
                try { await api('/livepref?mode=' + v); } catch (e) {}
                await refresh();
              },
            })
          : null,
        h(
          'div',
          { className: 'dsey-sec' },
          h('div', { className: 'dsey-sec-t' }, '对话框' + ((st.chat && st.chat.unread) ? '（' + st.chat.unread + ' 条没回）' : '')),
          h('div', { className: 'dsey-note' }, '看视频、一起玩的时候用：开一个小窗，你打字，我就在旁边直接回，不用等 QQ。'),
          h(
            'div',
            { className: 'dsey-foot' },
            h('button', { className: 'dsey-btn', onClick: openChatWin, disabled: busy }, st.chat && st.chat.open ? '窗口开着（再点一下）' : '打开对话框'),
            st.chat && st.chat.lastErr ? h('span', { className: 'dsey-err' }, st.chat.lastErr) : null,
          ),
        ),
        h(
          'div',
          { className: 'dsey-sec' },
          h(
            'div',
            { className: 'dsey-sec-t', style: { cursor: 'pointer' }, onClick: () => setHelp((v) => !v) },
            '怎么用 ' + (help ? '▾' : '▸') + '（点这里' + (help ? '收起' : '展开') + '）',
          ),
          help
            ? h(
                'div',
                { className: 'dsey-help' },
                h('div', null, '1. 先点右上角「打开」。两秒后出现帧数，就是眼睛在看了。'),
                h('div', null, '2. 平时什么都不用管。屏幕大变化时右上角会闪一条小提示，四秒半自己消失，不挡你操作。'),
                h('div', null, '3. 嫌吵：点「别看了」关掉提醒；或者点「改成挂面板」，只记账不打扰。想让我被叫醒，再切「改成叫醒我」。'),
                h('div', null, '4. 「最近大变化」是记账本：只在真的换前台窗口、或整屏内容大改时记一笔（视频在放、页面滚动不算）。'),
                h('div', null, '5. 参数不懂就别动，默认够用。改完立即生效；调坏了点「恢复默认」。'),
                h('div', null, '6. 「关掉」是真不录了——采集进程会被杀掉，不是装装样子。'),
                h('div', null, '7. 启动方式两种：「自动」＝DSH 一打开眼睛就跟着开；「手动」＝每次都要自己点「打开」。面板右下角切换。'),
                h('div', null, '8. 想让鲸鲸看刚才发生了什么，直接说「看看刚才」「刚才那一下点中没」。'),
                h('div', null, '9. 要做「一起看视频」那种实时聊：打开「对话框」，在小窗里打字回车，我会被叫醒并回到那个窗口里。'),
                h('div', null, '10. 「现在眼睛看到的」能切四种视角：实时帧、余光拼图、动作回声、聚焦裁切——就是模型实际拿到的图。画质和近层时长一改，预览跟着变；大小选关/小图/大图，选了什么重启也记得。'),
                h('div', null, '11. 「眼睛参数」上面有性能档：低 / 中 / 高，一键把六个参数一起换掉（低档给老机器省一半资源，代价是动作变粗、小字要凑近看）；拖任一滑块就变成「自定义」。'),
              )
            : null,
        ),
        h(Settings, null),
        h(
          'div',
          { className: 'dsey-sec' },
          h('div', { className: 'dsey-sec-t' }, '最近大变化' + (w.events && w.events.length ? '（' + w.events.length + '）' : '')),
          w.events && w.events.length
            ? w.events.slice().reverse().slice(0, 8).map((ev, i) =>
                h(
                  'div',
                  { className: 'dsey-evt', key: i },
                  h('span', { className: 'dsey-evt-t' }, new Date(ev.t).toLocaleTimeString('zh-CN', { hour12: false })),
                  h('span', { className: 'dsey-evt-s' }, ev.kind === 'window' ? '换窗口' : '画面大改'),
                  h('span', { className: 'dsey-evt-w' }, ev.title ? '「' + ev.title + '」' : ''),
                  h('span', { className: 'dsey-evt-w' }, ev.kind === 'window' || !ev.box ? '' : '(' + ev.box.join(',') + ')'),
                ),
              )
            : h('div', { className: 'dsey-note' }, '这段还没记到大幅变化。有事件只会出现在这里，不往聊天里投。'),
        ),
        h('div', { className: 'dsey-note' }, '关掉＝采集进程真被杀，屏幕上什么都不录；只留内存，不落盘。叫醒＝屏幕真的大变时插件投一条短提示给我。参数改完立即生效，下次打开眼睛也记得。'),
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

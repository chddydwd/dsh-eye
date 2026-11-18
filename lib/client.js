
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
      '.dsey-meta{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;opacity:.82;padding:6px 11px;border-radius:9px;background:rgba(10,16,24,.34)}',
      '.dsey-note{font-size:11.5px;opacity:.62;padding:0 4px}',
      '.dsey-err{font-size:12px;color:#ff6b60}',
      '.dsey-sec{margin-top:4px;padding:10px 12px;border-radius:10px;background:rgba(10,16,24,.42);border:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;gap:8px}',
      '.dsey-sec-t{font-size:12px;font-weight:600;opacity:.9}',
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

      const save = async () => {
        if (!draft) return;
        setBusy(true); setMsg('');
        try {
          const qs = KNOBS.map((kn) => kn.k + '=' + encodeURIComponent(draft[kn.k])).join('&');
          const r = await fetch(EYE + '/config?' + qs);
          const c = await r.json();
          setCfg(c); setDraft(c);
          setMsg('已生效 · 预计占用 ' + c.est_mem_mb + ' MB');
        } catch (e) { setMsg('保存失败：' + String((e && e.message) || e)); }
        setBusy(false);
      };

      if (!draft) return h('div', { className: 'dsey-sec' }, h('div', { className: 'dsey-sec-t' }, '眼睛参数'), h('div', { className: 'dsey-note' }, msg || '读取中…'));

      return h(
        'div',
        { className: 'dsey-sec' },
        h('div', { className: 'dsey-sec-t' }, '眼睛参数'),
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
          h('button', { className: 'dsey-btn', onClick: save, disabled: busy }, busy ? '…' : '保存'),
          h('button', { className: 'dsey-btn', onClick: () => { if (cfg && cfg.defaults) setDraft({ ...cfg.defaults }); } }, '恢复默认'),
          h('span', null, '现在：近 ' + (cfg ? cfg.near_frames : '-') + ' 张 / 远 ' + (cfg ? cfg.far_frames : '-') + ' 张 · 每帧 ' + (cfg ? cfg.frame_kb : '-') + 'KB · 约 ' + (cfg ? cfg.est_mem_mb : '-') + ' MB'),
        ),
        msg ? h('div', { className: 'dsey-note' }, msg) : null,
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

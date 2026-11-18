
/**
 * dsh-eye —— 鲸鲸的眼睛（宿主半侧）
 *
 * 眼睛本身是一个独立的 python 常驻进程（eye_serve.py，端口 13201）：ffmpeg 抓屏 20fps，
 * 压 JPEG 只留在内存里最近 15 秒，不落盘、不压视频。这里负责：起停它、把两个口子
 * （余光窗口 / 1:1 聚焦 / 动作回声）做成工具交给模型。
 *
 * 隐私红线：停 = 进程真被杀掉，不是挂个标志位；不留文件。
 */
import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const name = 'dsh-eye'
// sessionController 是「主动叫醒」用的（旧 see_now 那套：resolveAgent → followup → flush）
export const inject = ['tools', 'sessionController']

// 安装位置：全部走 homedir + eye.json，不写死任何人的路径（别人装也能跑）
const HOME = homedir()
const DSH_DIR = process.env.DSH_HOME || join(HOME, '.dsh')
const EYE_JSON = process.env.DSH_EYE_CONFIG || join(DSH_DIR, 'eye.json')

function readEyeCfg() {
  try {
    return JSON.parse(readFileSync(EYE_JSON, 'utf8'))
  } catch {
    return {}
  }
}
const EYE_CFG = readEyeCfg()
const EYE_PATHS = EYE_CFG.paths && typeof EYE_CFG.paths === 'object' ? EYE_CFG.paths : {}

// 眼睛脚本目录：DSH_EYE_HOME → eye.json 的 paths.dir → 空（空就是没配，会明确报错）
const EYE_HOME = process.env.DSH_EYE_HOME || EYE_PATHS.dir || ''

function pickPython() {
  const cand = [process.env.DSH_EYE_PYTHON, EYE_PATHS.python]
  const la = join(HOME, 'AppData', 'Local', 'Programs', 'Python')
  cand.push(join(la, 'Python312', 'python.exe'), join(la, 'Python311', 'python.exe'), join(la, 'Python313', 'python.exe'))
  cand.push('C:\\Python312\\python.exe', 'C:\\Python311\\python.exe')
  for (const c of cand) {
    if (c && existsSync(c)) return c
  }
  return 'python'
}

const PY = pickPython()
const CWD = EYE_HOME
const SCRIPT = EYE_HOME ? join(EYE_HOME, 'eye_serve.py') : ''
const TOAST = EYE_HOME ? join(EYE_HOME, 'eye_toast.py') : ''
const CHAT = EYE_HOME ? join(EYE_HOME, 'eye_chat.py') : ''
const DOCTOR = EYE_HOME ? join(EYE_HOME, 'eye_doctor.py') : ''
const BASE = 'http://127.0.0.1:13201'
const PREFIX = '/dsh-eye'

const state = { child: null, err: '', svc: null, startedAt: 0, lastLook: 0, sessionId: null, lastCallerAt: 0, autostart: false, chatChild: null }

/**
 * 主动叫醒（把旧 see_now 最大的优点吸过来）：钟放在插件里，只有屏幕**真的大变**才叫醒模型。
 *
 * 为什么不靠模型自己反复调工具：模型拿到图、回完话就停了，它不知道下一次该什么时候看。
 * 钟每 1.5 秒敲一次几乎不花钱；叫醒一次 = 投一条消息 = 模型跑一轮，这才贵。
 */
const watch = {
  on: true, gapSec: 25, threshold: 6, maxWakes: 3, maxPerHour: 12,
  lastWake: 0, wakes: 0, lastScore: 0, baseline: 0, lastErr: '', wakeTimes: [],
  // 大变化记到哪：'panel' = 只挂面板；'toast' = 在前台窗口上闪一条提示（不经过聊天框）；'wake' = 投消息叫醒我
  mode: 'panel', events: [], pendingAt: 0,
  // 灵敏度档位：每个人的容忍度不一样，现场能切。默认 balance
  alert: 'normal',
}
// 面板里「现在眼睛看到的」实时画面：off / small / big。有人嫌大，有人要看清
let liveMode = 'small'
// 灵敏度档位 → 判定用的倍率。quiet 只记很确定的（少打扰），sensitive 稍微一动就记（别漏）
const ALERT_PROF = {
  quiet: { switchMul: 1.6, contentMul: 2.0, label: '少打扰' },
  normal: { switchMul: 1.0, contentMul: 1.4, label: '平衡' },
  sensitive: { switchMul: 0.6, contentMul: 0.9, label: '别漏' },
}
function alertProf() { return ALERT_PROF[watch.alert] || ALERT_PROF.normal }
try {
  const raw = JSON.parse(readFileSync('C:\\Users\\Ddy\\.dsh\\eye.json', 'utf8'))
  if (typeof raw.watch === 'boolean') watch.on = raw.watch
  if (Number(raw.gapSec) > 0) watch.gapSec = Number(raw.gapSec)
  if (Number(raw.threshold) > 0) watch.threshold = Number(raw.threshold)
  if (Number(raw.maxWakes) >= 0) watch.maxWakes = Math.floor(Number(raw.maxWakes))
  if (Number(raw.maxPerHour) > 0) watch.maxPerHour = Math.floor(Number(raw.maxPerHour))
  if (raw.mode === 'wake' || raw.mode === 'panel' || raw.mode === 'toast') watch.mode = raw.mode
  if (raw.alert === 'quiet' || raw.alert === 'normal' || raw.alert === 'sensitive') watch.alert = raw.alert
  // 启动方式：true = DSH 一打开就自动开眼睛；false = 必须人为点「打开」
  if (typeof raw.autostart === 'boolean') state.autostart = raw.autostart
  // 上一次投过话的会话：重启后对话框也能直接叫醒我，不用先摸一次工具
  if (typeof raw.lastSession === 'string' && raw.lastSession) state.sessionId = raw.lastSession
  // 实时画面大小：重启后还记得
  if (raw.live === 'off' || raw.live === 'small' || raw.live === 'big') liveMode = raw.live
} catch (e) { /* 没有配置文件就用默认值 */ }

/** 把面板上改的东西写回 eye.json，重启 DSH 后还记得 */
function persistEye() {
  try {
    // 保留文件里本来有的键（paths.dir / paths.python 这些是安装器写的，丢了下次就起不来）
    let old = {}
    try { old = JSON.parse(readFileSync(EYE_JSON, 'utf8')) } catch {}
    writeFileSync(EYE_JSON, JSON.stringify({
      ...(old && typeof old === 'object' ? old : {}),
      watch: watch.on, mode: watch.mode, alert: watch.alert, gapSec: watch.gapSec, threshold: watch.threshold,
      maxWakes: watch.maxWakes, maxPerHour: watch.maxPerHour, autostart: state.autostart,
      live: liveMode,
      lastSession: state.sessionId || '',
    }, null, 2) + '\n', 'utf8')
  } catch (e) { /* 写不了就算了，别把插件搞挂 */ }
}

/** cordis 的 ctx 是 Proxy：服务没在 inject 里声明时 get 直接抛，所以一律包 try */
function serviceOf(ctx, name) {
  if (!ctx) return null
  try { if (typeof ctx.get === 'function') { const v = ctx.get(name); if (v) return v } } catch (e) {}
  try { return ctx[name] ?? null } catch (e) { return null }
}

function userMessage(text) {
  return { id: randomUUID(), role: 'user', content: [{ type: 'text', text: String(text ?? '') }], source: { kind: 'dsh-eye' } }
}

/** 叫醒：resolveAgent → followup（下一轮）→ sessions.flush。绝不抛。 */
async function wakeSession(sessionId, text) {
  const sc = serviceOf(ctx0, 'sessionController')
  if (!sc?.resolveAgent) return { ok: false, reason: 'no-session-controller' }
  if (!sessionId) return { ok: false, reason: 'no-session-id' }
  try {
    const resolved = await sc.resolveAgent(sessionId)
    if (!resolved || resolved.error || !resolved.agent) {
      return { ok: false, reason: String(resolved?.error?.message ?? resolved?.error ?? 'resolve-failed').slice(0, 140) }
    }
    const agent = resolved.agent
    try { agent.followup(userMessage(text)) } catch (e) { return { ok: false, reason: String((e && e.message) || e).slice(0, 140) } }
    try { const sessions = serviceOf(ctx0, 'sessions'); if (sessions?.flush) await sessions.flush(agent.session) } catch (e) {}
    return { ok: true }
  } catch (e) { return { ok: false, reason: String((e && e.message) || e).slice(0, 140) } }
}

/** 从工具执行上下文里记下「谁在跟我说话」——叫醒要投给这个会话，不能投给别人 */
function noteRun(run) {
  const session = run?.agent?.session
  const id = session?.header?.id ?? session?.id ?? null
  if (!id) return
  const depth = session?.header?.delegationDepth
  if (typeof depth === 'number' && depth > 0) return
  if (state.sessionId !== id) { state.sessionId = id; watch.wakes = 0; try { persistEye() } catch (e) {} }
  state.lastCallerAt = Date.now()
  if (watch.wakes > 0) watch.wakes = 0   // 我回应了（调了眼睛工具）＝叫醒了有人接，配额归零
}

const hist = []
let watchTimer = null
/** 这批采样里的中位数：当作「这个屏幕本来就在动的底噪」（DSH 界面有动画，静止也 4~8） */
function median(arr) {
  const a = arr.slice().sort((x, y) => x - y)
  return a.length ? a[Math.floor(a.length / 2)] : 0
}
async function tickWatch() {
  if (!watch.on || !state.sessionId) return
  if (!(await probe(700))) return
  let a = null
  try { a = await jget('/activity') } catch (e) { return }
  const score = Number(a.score) || 0
  watch.lastScore = score
  // 前台窗口切换是「硬事件」：画面变化可能只是视频在放、页面滚了一下，窗口换人才是真发生了什么
  const fg = a.fg && typeof a.fg === 'object' ? a.fg : null
  const fgHwnd = fg ? Number(fg.hwnd) || 0 : 0
  const fgTitle = fg ? String(fg.title || '') : String(a.title || '')
  const switched = !!(fgHwnd && fgHwnd !== watch.lastFg)
  if (fgHwnd) watch.lastFg = fgHwnd
  const prev = hist.slice()
  hist.push(score)
  if (hist.length > 40) hist.shift()
  if (prev.length < 10) return            // 先攒约 15 秒底噪，别一开机就乱叫
  const base = median(prev.slice(-30))
  watch.baseline = Math.round(base * 100) / 100
  const need = Math.max(watch.threshold, base * 2.5)
  const prof = alertProf()
  const now = Date.now()
  // 只有两种算事：①换了前台窗口（且画面确实变了）②画面变化远超底噪（比如整页刷新）
  const hardSwitch = switched && score >= Math.max(watch.threshold, base * 1.2) * prof.switchMul
  const bigContent = score >= need * prof.contentMul
  if (!hardSwitch && !bigContent) { watch.pendingAt = 0; return }
  // 只冲一拍的是「界面自己换了张脸」（切面板、页面重排）；要连着两拍都高才算事
  if (!watch.pendingAt || now - watch.pendingAt > 5000) {
    watch.pendingAt = now; return
  }
  watch.pendingAt = 0
  // 一直在高（视频、拖窗口）不算「发生了什么」：要求前几拍是安静的
  if (prev.slice(-5, -1).some((v) => v >= need * Math.min(1, prof.contentMul))) return
  if (now - watch.lastWake < watch.gapSec * 1000) return
  watch.wakeTimes = watch.wakeTimes.filter((t) => now - t < 3600e3)
  if (watch.wakeTimes.length >= watch.maxPerHour) return
  const ev = {
    t: now,
    kind: hardSwitch ? 'window' : 'content',
    score: Math.round(score * 100) / 100,
    box: Array.isArray(a.box) ? a.box.map((v) => Math.round(Number(v) || 0)) : null,
    title: String(fgTitle || a.title || '').slice(0, 60),
  }
  watch.lastWake = now
  watch.wakeTimes.push(now)
  // 事件一律记进面板（默认就是这样：挂后台，不往聊天里投）
  watch.events.push(ev)
  if (watch.events.length > 30) watch.events.shift()
  if (watch.mode === 'panel') return
  const title = String(a.title || '').slice(0, 40)
  const detail = 'score ' + Math.round(score * 100) / 100 + (a.box ? ' · 变化框 (' + a.box.join(',') + ')' : '') + (title ? ' · 前台「' + title + '」' : '')
  if (watch.mode === 'toast') { spawnToast('眼睛 · 屏幕大幅变化', detail); return }
  if (watch.maxWakes > 0 && watch.wakes >= watch.maxWakes) return
  const box = Array.isArray(a.box) ? '，变化在 (' + a.box.join(',') + ')' : ''
  const where = a.title ? '，前台是「' + String(a.title).slice(0, 40) + '」' : ''
  const text = '眼睛：屏幕刚刚大幅变了（score ' + score + box + where + '）。\n'
    + '要看就 eye_window 看最近 10 秒、eye_echo 看刚才那一下；不想被叫就 eye_watch({on:false})。'
  const r = await wakeSession(state.sessionId, text)
  if (r.ok) { watch.wakes += 1 } else { watch.lastErr = String(r.reason || '') }
}

/** 没配脚本目录时给一句人话，而不是 spawn 一个空路径 */
function missingHome() {
  if (EYE_HOME) return false
  state.err = 'eye-home-missing: 先配眼睛脚本目录（环境变量 DSH_EYE_HOME，或 ~/.dsh/eye.json 里写 {"paths":{"dir":"…"}}）'
  return true
}

/** 在最前面闪一条提示：独立 python 小窗（置顶、不抢焦点、4.5 秒自己消失），不经过聊天框 */
function spawnToast(title, detail) {
  if (missingHome()) return false
  try {
    const p = spawn(PY, [TOAST, String(title || ''), String(detail || ''), '4.5'], { cwd: CWD, stdio: 'ignore', windowsHide: true })
    p.on('error', () => {})
    p.unref?.()
    return true
  } catch (e) { watch.lastErr = 'toast-fail: ' + String((e && e.message) || e); return false }
}

// ---- 对话框：用户开的小窗（eye_chat.py），消息经 eye_serve.py 的 /chat 中转，不走 QQ ----
const chat = { open: false, unread: 0, lastId: 0, lastErr: '', lastWake: 0, alive: false, hwnd: 0 }
/** 小窗是否真的在（插件起的，或者外面起的都算） */
function chatOpen() { return !!(state.chatChild || chat.alive) }
/** 小窗每 15 秒报一次心跳，这里问一下它还在不在 */
async function winPing() {
  try {
    const j = await jget('/chat/win')
    chat.alive = !!j.alive
    chat.hwnd = Number(j.hwnd) || 0
    if (chat.alive) chat.open = true
    else if (!state.chatChild) chat.open = false
  } catch (e) { chat.alive = false }
}
function spawnChat() {
  if (missingHome()) { chat.lastErr = state.err; return false }
  if (state.chatChild) return true
  try {
    const c = spawn(PY, [CHAT], { cwd: CWD, stdio: 'ignore', windowsHide: true })
    state.chatChild = c
    chat.open = true
    c.on('exit', () => { state.chatChild = null; chat.open = false })
    c.on('error', (e) => { state.chatChild = null; chat.open = false; chat.lastErr = String((e && e.message) || e) })
    return true
  } catch (e) { chat.lastErr = 'chat-fail: ' + String((e && e.message) || e); return false }
}
async function openChat() {
  await ensureEye()
  if (state.chatChild) return true
  await winPing()
  if (chat.alive) return true   // 窗口在（可能是外面起的），不再重复 spawn
  return spawnChat()
}
async function chatPost(text) {
  const r = await fetch(BASE + '/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: String(text), from: 'me' }) })
  if (!r.ok) throw new Error('eye HTTP ' + r.status + ' for /chat')
  return r.json()
}
/** 对话框的钟：用户在小窗里说的话，马上投给我（1.2 秒一拍，比 QQ 快得多） */
async function tickChat() {
  if (!state.sessionId) return
  if (!(await probe(600))) return
  let r = null
  try { r = await jget('/chat?since=' + chat.lastId) } catch (e) { return }
  const msgs = Array.isArray(r.msgs) ? r.msgs : []
  for (const m of msgs) {
    const id = Number(m.id) || 0
    if (id <= chat.lastId) continue
    chat.lastId = id
    if (m.from !== 'user') continue
    const text = '对话框（用户在眼睛的小窗里说，不在 QQ）：' + String(m.text || '')
      + '\n回他就用 eye_chat({say:"…"})，话会直接显示在他那个窗口里。'
    const w = await wakeSession(state.sessionId, text)
    if (w.ok) chat.lastWake = Date.now()
    else { chat.lastErr = String(w.reason || ''); chat.unread += 1 }
  }
}

async function probe(timeout = 900) {
  try { const r = await fetch(BASE + '/state', { signal: AbortSignal.timeout(timeout) }); return r.ok } catch (e) { return false }
}

/** 自检：跑一遍 eye_doctor.py，把它的几行人话原样交给面板 */
function runDoctor(port) {
  return new Promise((resolve) => {
    if (missingHome() || !DOCTOR || !existsSync(DOCTOR)) {
      resolve({ ok: false, text: '找不到 eye_doctor.py：先配眼睛脚本目录（环境变量 DSH_EYE_HOME，或 ~/.dsh/eye.json 的 paths.dir）' })
      return
    }
    let out = '', err = ''
    let p = null
    try {
      p = spawn(PY, port ? [DOCTOR, String(port)] : [DOCTOR], { cwd: CWD, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    } catch (e) {
      resolve({ ok: false, text: '起不来：' + ((e && e.message) || e) })
      return
    }
    const to = setTimeout(() => { try { p.kill() } catch (e) {} }, 25000)
    p.stdout.on('data', (d) => { out += String(d) })
    p.stderr.on('data', (d) => { err += String(d) })
    p.on('close', (code) => {
      clearTimeout(to)
      const text = (out || err || '').trim() || '（自检没有输出）'
      resolve({ ok: code === 0, code, text })
    })
  })
}

function spawnServer() {
  if (missingHome()) return
  if (state.child) return
  try {
    const c = spawn(PY, [SCRIPT], { cwd: CWD, stdio: 'ignore', windowsHide: true })
    state.child = c; state.startedAt = Date.now()
    c.on('exit', () => { state.child = null })
    c.on('error', (e) => { state.err = String((e && e.message) || e); state.child = null })
  } catch (e) { state.err = String((e && e.message) || e) }
}

function killServer() {
  const c = state.child
  if (!c) return
  state.child = null
  try { spawn('taskkill', ['/pid', String(c.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }) } catch (e) {}
}

async function ensureEye() {
  if (await probe()) return true
  spawnServer()
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 300))
    if (await probe()) return true
  }
  return false
}

async function jget(p) {
  const r = await fetch(BASE + p, { signal: AbortSignal.timeout(15000) })
  if (!r.ok) throw new Error('eye HTTP ' + r.status + ' for ' + p)
  return r.json()
}

async function bget(p) {
  const r = await fetch(BASE + p, { signal: AbortSignal.timeout(20000) })
  if (!r.ok) throw new Error('eye HTTP ' + r.status + ' for ' + p)
  return Buffer.from(await r.arrayBuffer())
}

/** 把 png 交给宿主的 attachments 服务，返回工具结果（images 会被界面/模型当附件看到） */
async function attach(ctx, buf, fileName, text, meta = {}) {
  let svc = state.svc
  if (!svc) {
    try { svc = ctx.get ? ctx.get('attachments') : null } catch (e) {}
  }
  if (!svc || !svc.saveImage) return { text: text + '\n（拿到图了，但宿主没有 attachments 服务，交不上去）', meta: { ...meta, ok: false } }
  try {
    const ref = await svc.saveImage.call(svc, { data: buf, mediaType: 'image/png', name: fileName })
    return { images: [ref], text, meta: { ...meta, ok: true, bytes: buf.length } }
  } catch (e) {
    return { text: text + '\n（交给宿主失败：' + ((e && e.message) || e) + '）', meta: { ...meta, ok: false } }
  }
}

const OUT_IMAGE = {
  schema: { type: 'object', additionalProperties: true, properties: {} },
  render: (_args, value) => [{ type: 'text', text: String((value && value.text) || '') }],
}

const TOOLS = [
  {
    name: 'eye_status',
    description: '看眼睛现在的状态：在不在采集、抓到多少帧、多少 fps、内存环跨多少秒、光标在哪、上一次点击多久以前。',
    parameters: { type: 'object', additionalProperties: false, properties: {} },
    output: {
      schema: { type: 'object', additionalProperties: true, properties: {} },
      render: (_a, v) => [{ type: 'text', text: String((v && v.text) || '') }],
    },
    async execute() {
      if (!(await probe())) return { text: '眼睛是关着的（采集进程没起）。想开就调 eye_toggle({on:true})。' }
      try {
        const s = await jget('/state')
        return {
          text: '眼睛开着：' + s.frames + ' 帧 / ' + s.fps + 'fps / 环跨 ' + s.span_sec + ' 秒 / 屏幕 ' + s.size.join('x')
            + ' / 光标 (' + s.cursor.join(',') + ') / 点击记录 ' + s.clicks + ' 次'
            + (s.last_click_ago != null ? '（最近一次 ' + s.last_click_ago + ' 秒前）' : '')
            + '\n记录去处：' + (watch.mode === 'wake' ? '叫醒我（投一条消息到聊天）' : '只挂在这个面板里（不投聊天），最近记了 ' + watch.events.length + ' 条')
            + '\n主动叫醒：' + (watch.on ? '开（阈值 ' + watch.threshold + ' / 最短间隔 ' + watch.gapSec + ' 秒 / 连续未回应上限 ' + watch.maxWakes + ' 次 / 每小时 ' + watch.maxPerHour + ' 次）' : '关')
            + '\n上一拍变化 score ' + watch.lastScore + '（底噪 ' + watch.baseline + '，超过 ' + Math.max(watch.threshold, Math.round(watch.baseline * 2.5 * 100) / 100) + ' 才叫）' + (watch.lastErr ? '，上次叫醒失败：' + watch.lastErr : ''),
          meta: { ...s, watch },
        }
      } catch (e) { return { text: '看眼睛状态失败：' + ((e && e.message) || e) } }
    },
  },
  {
    name: 'eye_toggle',
    description: '开或关眼睛（隐私开关）。关＝真把采集进程杀掉，屏幕上什么都不录。开＝重新起采集，约 2 秒后可用。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: { on: { type: 'boolean', description: 'true 开 / false 关' } },
      required: ['on'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true, properties: {} },
      render: (_a, v) => [{ type: 'text', text: String((v && v.text) || '') }],
    },
    async execute({ on }) {
      if (on) {
        const ok = await ensureEye()
        return { text: ok ? '眼睛开了：20fps 只留最近 15 秒，全在内存里。' : '起不来：' + (state.err || '进程没响应，看日志') }
      }
      killServer()
      for (let i = 0; i < 10; i++) { await new Promise(r => setTimeout(r, 200)); if (!(await probe(400))) break }
      return { text: (await probe(400)) ? '没关掉，进程还在。' : '眼睛关了：采集进程已杀，内存环清空，什么都没留。' }
    },
  },
  {
    name: 'eye_window',
    description: '看最近一段时间的「余光窗口」：把 N 秒压成一张带编号的缩略图拼图（默认 10 秒 100 格），'
      + '能一眼看出哪一格开始动了。拿到异常格子后用 eye_cell({i}) 回取那一格的 1:1 原像素。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        span: { type: 'number', description: '覆盖最近多少秒，默认 10' },
        n: { type: 'number', description: '拼多少格，默认 100' },
        cols: { type: 'number', description: '每行几格，默认 10' },
      },
    },
    output: OUT_IMAGE,
    async execute({ span, n, cols }) {
      if (!(await ensureEye())) return { text: '眼睛起不来：' + (state.err || '未知原因') }
      const sp = Number(span) > 0 ? Number(span) : 10
      const nn = Number(n) > 0 ? Number(n) : 100
      const cc = Number(cols) > 0 ? Number(cols) : 10
      try {
        const info = await jget('/diff?span=' + sp + '&n=' + nn)
        const buf = await bget('/window?span=' + sp + '&n=' + nn + '&cols=' + cc)
        state.lastLook = Date.now()
        const hot = (info.hot_cells || []).slice(0, 20)
        return attach(ctx0, buf, 'eye-window-' + Date.now() + '.png',
          '余光窗口：最近 ' + sp + ' 秒 / ' + nn + ' 格（每行 ' + cc + '）'
            + (hot.length ? '\n变动明显的格子：' + hot.join(', ') + '（想看哪格就 eye_cell({i:格子号})）' : '\n这段时间画面基本没动。'),
          { span: sp, n: nn, hot })
      } catch (e) { return { text: '取余光窗口失败：' + ((e && e.message) || e) } }
    },
  },
  {
    name: 'eye_cell',
    description: '按余光窗口里的编号，回取那一格的 1:1 原像素（可裁剪到某块区域）。这是「凑近看」。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        i: { type: 'number', description: '格子编号（0 起）' },
        span: { type: 'number', description: '与 eye_window 用的 span 保持一致，默认 10' },
        n: { type: 'number', description: '与 eye_window 用的 n 保持一致，默认 100' },
        fw: { type: 'number', description: '裁多宽，默认 700' },
        fh: { type: 'number', description: '裁多高，默认 393' },
        cx: { type: 'number', description: '裁剪中心 x（屏幕像素），不给就居中' },
        cy: { type: 'number', description: '裁剪中心 y（屏幕像素），不给就居中' },
        atCursor: { type: 'boolean', description: 'true = 裁在光标现在的位置' },
      },
      required: ['i'],
    },
    output: OUT_IMAGE,
    async execute(a) {
      if (!(await ensureEye())) return { text: '眼睛起不来：' + (state.err || '未知原因') }
      const sp = Number(a.span) > 0 ? Number(a.span) : 10
      const nn = Number(a.n) > 0 ? Number(a.n) : 100
      let q = '/cell?i=' + (Number(a.i) || 0) + '&span=' + sp + '&n=' + nn
      if (a.fw || a.fh || a.cx || a.cy || a.atCursor) {
        if (a.atCursor) q = '/fovea_at_cursor?fw=' + (Number(a.fw) || 700) + '&fh=' + (Number(a.fh) || 393)
        else q += '&fw=' + (Number(a.fw) || 700) + '&fh=' + (Number(a.fh) || 393)
          + (a.cx != null ? '&cx=' + Math.round(Number(a.cx)) : '') + (a.cy != null ? '&cy=' + Math.round(Number(a.cy)) : '')
      }
      try {
        const buf = await bget(q)
        return attach(ctx0, buf, 'eye-cell-' + Date.now() + '.png', '第 ' + (Number(a.i) || 0) + ' 格的 1:1 画面' + (a.atCursor ? '（裁在光标处）' : ''), { i: Number(a.i) || 0 })
      } catch (e) { return { text: '取那一格失败：' + ((e && e.message) || e) } }
    },
  },
  {
    name: 'eye_echo',
    description: '动作回声：拿最近一次鼠标点击，自动给出点击前 / 点击后的几帧（裁在点击的位置），用来看刚才那一下有没有点中、界面有没有反应。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        before: { type: 'number', description: '点击前往前取几秒，默认 1' },
        after: { type: 'number', description: '点击后往后取几秒，默认 1.2' },
      },
    },
    output: OUT_IMAGE,
    async execute({ before, after }) {
      if (!(await ensureEye())) return { text: '眼睛起不来：' + (state.err || '未知原因') }
      const bf = Number(before) > 0 ? Number(before) : 1
      const af = Number(after) > 0 ? Number(after) : 1.2
      try {
        const info = await jget('/echo_info?before=' + bf + '&after=' + af)
        if (info && info.error) return { text: '还没有点击记录（眼睛要在我动手之后才有的看）。' }
        const buf = await bget('/echo_focus?before=' + bf + '&after=' + af)
        const c = info.click || {}
        return attach(ctx0, buf, 'eye-echo-' + Date.now() + '.png',
          '动作回声：点 (' + c.x + ',' + c.y + ') ' + (c.title ? '在「' + c.title + '」' : '') + '，'
            + '四格是点击前 ' + bf + ' 秒 / 点击前一刻 / 点击后一刻 / 点击后 ' + af + ' 秒',
          { click: c, frames: info.frames })
      } catch (e) { return { text: '取动作回声失败：' + ((e && e.message) || e) } }
    },
  },
  {
    name: 'eye_watch',
    description: '开关「主动叫醒」：屏幕真的大变时插件会自己叫醒我一次（投一条短提示，不塞图，省 token）。'
      + '参数都能现场改：on 开关、gap 两次叫醒最短间隔秒数、threshold 变化阈值（越大越不敏感）、max 连续未回应几次就停。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        on: { type: 'boolean', description: 'true 开 / false 关' },
        gap: { type: 'number', description: '两次叫醒最短间隔秒数（默认 25）' },
        threshold: { type: 'number', description: '变化阈值，score 0~255 尺度（默认 6，越大越少叫）' },
        max: { type: 'number', description: '连续几次没回应就停（默认 3）' },
        mode: { type: 'string', enum: ['panel', 'toast', 'wake'], description: "大变化记到哪：'panel' 只挂面板（默认）、'toast' 在前台窗口上闪一条提示（不经过聊天框）、'wake' 投消息叫醒我" },
        alert: { type: 'string', enum: ['quiet', 'normal', 'sensitive'], description: "灵敏度档位：'quiet' 少打扰（只记很确定的）、'normal' 平衡（默认）、'sensitive' 别漏（稍微一动就记）" },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true, properties: {} },
      render: (_a, v) => [{ type: 'text', text: String((v && v.text) || '') }],
    },
    async execute({ on, gap, threshold, max, mode, alert }) {
      if (typeof on === 'boolean') watch.on = on
      if (Number(gap) > 0) watch.gapSec = Number(gap)
      if (Number(threshold) > 0) watch.threshold = Number(threshold)
      if (Number(max) >= 0) watch.maxWakes = Math.floor(Number(max))
      if (mode === 'panel' || mode === 'toast' || mode === 'wake') watch.mode = mode
      if (alert === 'quiet' || alert === 'normal' || alert === 'sensitive') {
        watch.alert = alert; watch.pendingAt = 0; hist.length = 0
      }
      return {
        text: '大变化记录：' + (watch.mode === 'wake' ? '投消息叫醒我' : watch.mode === 'toast' ? '在前台窗口闪一条提示（不经过聊天框）' : '只挂面板，不投聊天') + '（面板里现在 ' + watch.events.length + ' 条）'
          + '\n主动叫醒：' + (watch.on ? '开' : '关')
          + '（灵敏度 ' + alertProf().label + ' / 阈值 ' + watch.threshold + ' / 间隔 ' + watch.gapSec + ' 秒 / 连续未回应上限 ' + watch.maxWakes + ' 次 / 每小时 ' + watch.maxPerHour + ' 次）'
          + '\n最近一拍变化 score ' + watch.lastScore + (state.sessionId ? '' : '\n还没记到会话 id：我要先调一次眼睛工具，它才知道把话投给谁。'),
        meta: { ...watch },
      }
    },
  },
  {
    name: 'eye_chat',
    description: '眼睛的「对话框」小窗（不经过 QQ）：看视频/一起玩的时候用它跟用户实时聊。open:true 打开小窗；say:"…" 把我的话发到小窗里（用户马上能看到）；都不传就查状态。用户在小窗里说的话我会被自动叫醒。',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        open: { type: 'boolean', description: 'true = 打开那个小窗（眼睛没开也会顺便开起来）' },
        say: { type: 'string', description: '要发到小窗里的话' },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true, properties: {} },
      render: (_a, v) => [{ type: 'text', text: String((v && v.text) || '') }],
    },
    async execute({ open, say }) {
      let sent = 0
      if (say) {
        try { await chatPost(say); sent = 1; chat.unread = 0 } catch (e) { return { text: '对话框没接上：' + ((e && e.message) || e) } }
      }
      if (open) await openChat()
      return {
        text: '对话框：' + (chatOpen() ? '开着' : '没开（eye_chat({open:true}) 打开）')
          + (sent ? '，已发 1 条' : '') + (chat.unread ? '，还有 ' + chat.unread + ' 条没回' : '')
          + (chat.lastErr ? '\n上次出错：' + chat.lastErr : ''),
        meta: { ...chat, open: chatOpen() },
      }
    },
  },
]

let ctx0 = null

export function apply(ctx) {
  ctx0 = ctx
  const disposers = []
  try {
    ctx.inject(['attachments'], (scoped) => { state.svc = scoped.attachments })
  } catch (e) {}
  for (const def of TOOLS) {
    try {
      const orig = def.execute
      def.execute = async (a, run) => { try { noteRun(run) } catch (e) {} return orig(a, run) }
      disposers.push(ctx.tools.register(def))
    } catch (e) {
      try { ctx.logger.warn('[dsh-eye] 工具注册失败 ' + def.name + '：' + ((e && e.message) || e)) } catch (e2) {}
    }
  }
  // 会话归属：会话里有任何动静就记住它（对话框叫醒要投给「正在跟我说话的那个会话」）
  try {
    disposers.push(ctx.on('session/event', (session) => {
      const id = session?.header?.id ?? session?.id ?? null
      if (!id || id === state.sessionId) return
      state.sessionId = id
      try { persistEye() } catch (e) {}
    }))
  } catch (e) {}
  // 叫醒的钟：每 1.5 秒敲一次（几乎不花钱），只有屏幕真的大变才投一条消息
  try {
    watchTimer = setInterval(() => { void tickWatch() }, 1500)
    watchTimer.unref?.()
    const chatTimer = setInterval(() => { void tickChat() }, 1200)
    chatTimer.unref?.()
    disposers.push(() => { try { clearInterval(chatTimer) } catch (e) {} })
    disposers.push(() => { try { clearInterval(watchTimer) } catch (e) {} })
    // 小窗心跳：窗口还开着没，跟有没有会话无关
    const winTimer = setInterval(() => { void winPing() }, 4000)
    winTimer.unref?.()
    disposers.push(() => { try { clearInterval(winTimer) } catch (e) {} })
  } catch (e) {}
  // 界面：把 client.js 塞进页面（工作台同款做法），左侧栏入口在客户端里注册
  try {
    const loader = '(function(){try{var d=document.body||document.documentElement;if(!d)return;'
      + 'if(window.__dshEye)return;var s=document.createElement("script");s.src="' + PREFIX + '/client.js?v="+Date.now();'
      + 's.onerror=function(){};d.appendChild(s)}catch(e){}})()'
    disposers.push(ctx.on('webserver/index-inject', (table) => {
      try {
        if (!Array.isArray(table)) return
        for (const row of table) if (row && typeof row.text === 'string' && row.text.indexOf(PREFIX + '/client.js') >= 0) return
        table.push({ kind: 'script', placement: 'body', text: loader })
      } catch (e) {}
    }))
  } catch (e) {}
  // 路由：/dsh-eye/client.js（界面脚本）+ /dsh-eye/state + /dsh-eye/toggle
  try {
    ctx.inject(['webServer'], (scoped) => {
      try {
        disposers.push(scoped.webServer.register({ kind: 'prefix', path: PREFIX, handler: makeHandler() }))
      } catch (e) {
        try { ctx.logger.warn('[dsh-eye] 路由注册失败：' + ((e && e.message) || e)) } catch (e2) {}
      }
    })
  } catch (e) {}
  try { ctx.logger.info('[dsh-eye] 已加载（工具 eye_* + /dsh-eye 路由）') } catch (e) {}
  // 自动模式：DSH 一打开就把眼睛起起来（手动模式什么都不做，等我/你点「打开」）
  if (state.autostart) setTimeout(() => { void ensureEye() }, 1500)
  return () => {
    for (const d of disposers.reverse()) { try { typeof d === 'function' ? d() : (d && d.dispose && d.dispose()) } catch (e) {} }
  }
}

// 路由：给界面看的状态与开关；client.js 从自己包里读
function makeHandler() {
  return async (req, res) => {
    const url = String((req && req.url) || '')
    const path = url.split('?')[0]
    try {
      if (path.endsWith('/state')) {
        const alive = await probe()
        let s = null
        if (alive) { try { s = await jget('/state') } catch (e) {} }
        return json(res, { ok: true, alive, state: s, autostart: state.autostart, live: liveMode, chat: { open: chatOpen(), unread: chat.unread, lastId: chat.lastId, lastErr: chat.lastErr }, watch: { on: watch.on, alert: watch.alert, gapSec: watch.gapSec, threshold: watch.threshold, maxWakes: watch.maxWakes, lastScore: watch.lastScore, wakes: watch.wakes, lastErr: watch.lastErr, mode: watch.mode, events: watch.events.slice(-15) }, err: state.err })
      }
      if (path.endsWith('/watch')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        if (q.get('on') === '1' || q.get('on') === 'true') watch.on = true
        if (q.get('on') === '0' || q.get('on') === 'false') watch.on = false
        if (Number(q.get('gap')) > 0) watch.gapSec = Number(q.get('gap'))
        if (Number(q.get('threshold')) > 0) watch.threshold = Number(q.get('threshold'))
        const md = q.get('mode')
        if (md === 'panel' || md === 'toast' || md === 'wake') watch.mode = md
        const al = q.get('alert')
        if (al === 'quiet' || al === 'normal' || al === 'sensitive') { watch.alert = al; watch.pendingAt = 0; hist.length = 0 }
        persistEye()
        return json(res, { ok: true, watch: { on: watch.on, alert: watch.alert, gapSec: watch.gapSec, threshold: watch.threshold, mode: watch.mode } })
      }
      if (path.endsWith('/livepref')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        const v = q.get('mode')
        if (v === 'off' || v === 'small' || v === 'big') liveMode = v
        persistEye()
        return json(res, { ok: true, live: liveMode })
      }
      if (path.endsWith('/chat')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        if (q.get('open') === '1') { const ok = await openChat(); return json(res, { ok, chat: { open: chatOpen(), unread: chat.unread, lastErr: chat.lastErr } }) }
        return json(res, { ok: true, chat: { open: chatOpen(), unread: chat.unread, lastId: chat.lastId, lastErr: chat.lastErr } })
      }
      if (path.endsWith('/autostart')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        state.autostart = q.get('on') === '1' || q.get('on') === 'true'
        persistEye()
        return json(res, { ok: true, autostart: state.autostart })
      }
      if (path.endsWith('/toggle')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        const on = q.get('on') === '1' || q.get('on') === 'true'
        if (on) { const ok = await ensureEye(); return json(res, { ok, alive: ok, err: state.err }) }
        killServer(); await new Promise(r => setTimeout(r, 400))
        return json(res, { ok: !(await probe(400)), alive: await probe(400) })
      }
      if (path.endsWith('/doctor')) {
        const q = new URLSearchParams(url.split('?')[1] || '')
        // 端口优先听请求头里的（桌面端窗口 location.port 可能为空），显式参数兜底
        const host = String((req && req.headers && (req.headers.host || req.headers.Host)) || '')
        const hostPort = (host.match(/:([0-9]+)$/) || [])[1] || ''
        const port = String(q.get('port') || '').replace(/[^0-9]/g, '') || hostPort
        const out = await runDoctor(port)
        return json(res, { ...out, port: port || '(none)' })
      }
      if (path.endsWith('/client.js')) {
        const body = await readClient()
        res.statusCode = 200
        res.setHeader('Content-Type', 'application/javascript; charset=utf-8')
        res.setHeader('Cache-Control', 'no-cache')
        return res.end(body)
      }
      res.statusCode = 404
      return res.end('not found')
    } catch (e) {
      return json(res, { ok: false, error: String((e && e.message) || e) })
    }
  }
}

function json(res, o) {
  const body = JSON.stringify(o)
  res.statusCode = 200
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(body)
}

async function readClient() {
  const { readFile } = await import('node:fs/promises')
  const { fileURLToPath } = await import('node:url')
  const { dirname, join } = await import('node:path')
  const here = dirname(fileURLToPath(import.meta.url))
  return readFile(join(here, 'client.js'), 'utf8')
}

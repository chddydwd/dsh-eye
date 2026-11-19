/**
 * dsh-eye 环境准备（面板上的「一键准备」）
 *
 * 普通用户 dsh plugin add 之后打不开，八成卡在四件事上：
 *   1) 没装 Python 3 2) 装了但缺 numpy / pillow / mss 3) 没 ffmpeg 4) eye.json 里没写脚本路径
 * 这里把这四件事查清：能自己修的修（补依赖、写路径），修不了的给人话步骤。
 * 全部本地执行；不碰 DSH 配置、不动 profile、不下载插件以外的东西。
 */
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
export const PLUGIN_ROOT = dirname(HERE)          // 插件根目录（lib 的上一级）
export const BUNDLED_PY = join(PLUGIN_ROOT, 'python')
const HOME = homedir()
const DSH_DIR = process.env.DSH_HOME || join(HOME, '.dsh')
const EYE_JSON = process.env.DSH_EYE_CONFIG || join(DSH_DIR, 'eye.json')
const REQ = join(BUNDLED_PY, 'requirements.txt')

function readCfg() {
  try { const j = JSON.parse(readFileSync(EYE_JSON, 'utf8')); return j && typeof j === 'object' ? j : {} } catch { return {} }
}
export function readPaths() {
  const j = readCfg()
  return j.paths && typeof j.paths === 'object' ? j.paths : {}
}

/** 跑一条命令，收 stdout/stderr；超时直接杀掉，绝不挂住面板 */
function run(cmd, args, timeout = 20000) {
  return new Promise((resolve) => {
    let out = '', err = '', done = false
    const finish = (o) => { if (!done) { done = true; resolve(o) } }
    let p
    try { p = spawn(cmd, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] }) }
    catch (e) { resolve({ ok: false, code: -1, out: '', err: String((e && e.message) || e) }); return }
    const to = setTimeout(() => { try { p.kill() } catch {} ; finish({ ok: false, code: -2, out, err: (err + ' timeout') }) }, timeout)
    p.stdout.on('data', (d) => { out += String(d) })
    p.stderr.on('data', (d) => { err += String(d) })
    p.on('error', (e) => { clearTimeout(to); finish({ ok: false, code: -1, out, err: String((e && e.message) || e) }) })
    p.on('close', (c) => { clearTimeout(to); finish({ ok: c === 0, code: c, out, err }) })
  })
}

function firstLine(s) { return String(s || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean)[0] || '' }

/** 找 Python：先看 eye.json 里记的，再看常见安装位置，最后 where / py -3 */
async function findPython() {
  const paths = readPaths()
  const cand = []
  if (process.env.DSH_EYE_PYTHON) cand.push(process.env.DSH_EYE_PYTHON)
  if (paths.python) cand.push(paths.python)
  const la = join(HOME, 'AppData', 'Local', 'Programs', 'Python')
  for (const v of ['312', '311', '313', '310']) cand.push(join(la, 'Python' + v, 'python.exe'))
  cand.push('C:\\Python312\\python.exe', 'C:\\Python311\\python.exe')
  for (const c of cand) { if (c && existsSync(c)) return c }
  const w = await run('where', ['python'])
  if (w.ok) {
    for (const line of w.out.split(/\r?\n/)) {
      const s = line.trim()
      if (/\.exe$/i.test(s) && existsSync(s)) return s
    }
  }
  const py = await run('py', ['-3', '-c', 'import sys;print(sys.executable)'])
  if (py.ok) { const s = firstLine(py.out); if (s && existsSync(s)) return s }
  return ''
}

async function pythonVersion(py) {
  const r = await run(py, ['-c', "import sys;print('%d.%d' % sys.version_info[:2])"])
  if (!r.ok) return ''
  return firstLine(r.out)
}

const DEPS = ['numpy', 'PIL', 'mss']
async function missingDeps(py) {
  const r = await run(py, ['-c', 'import ' + DEPS.join(', ')])
  if (r.ok) return { ok: true, missing: [] }
  // 分个查，才知道到底缺哪个
  const missing = []
  for (const name of DEPS) {
    const one = await run(py, ['-c', 'import ' + name])
    if (!one.ok) missing.push(name === 'PIL' ? 'pillow' : name)
  }
  if (!missing.length) missing.push('未知（导入报错，看日志）')
  return { ok: false, missing, detail: firstLine(r.err) }
}

async function findFfmpeg() {
  const r = await run('ffmpeg', ['-version'], 10000)
  if (r.ok) return { ok: true, version: firstLine(r.out) }
  const w = await run('where', ['ffmpeg'], 10000)
  if (w.ok) { const s = firstLine(w.out); if (s) return { ok: true, path: s } }
  return { ok: false }
}

/** 只查不改 */
export async function check() {
  const items = []
  const paths = readPaths()
  const dir = process.env.DSH_EYE_HOME || paths.dir || ''
  const scriptOk = !!dir && existsSync(join(dir, 'eye_serve.py'))
  const bundledOk = existsSync(join(BUNDLED_PY, 'eye_serve.py'))
  items.push({
    key: 'dir', label: '眼睛脚本', ok: scriptOk,
    detail: scriptOk ? dir : (bundledOk ? '还没配路径（点一键准备自动写）' : '插件里没有 python 目录，重装一遍'),
  })
  const py = await findPython()
  let ver = ''
  let pyOk = false
  if (py) {
    ver = await pythonVersion(py)
    const major = Number(String(ver).split('.')[0] || 0)
    const minor = Number(String(ver).split('.')[1] || 0)
    pyOk = major === 3 && minor >= 9
  }
  items.push({
    key: 'python', label: 'Python', ok: pyOk,
    detail: py ? (ver || '?') + ' · ' + py : '没找到 Python 3（要 3.9 以上）',
  })
  let deps = { ok: false, missing: ['先装 Python'] }
  if (py) deps = await missingDeps(py)
  items.push({
    key: 'deps', label: '依赖', ok: deps.ok,
    detail: deps.ok ? 'numpy / pillow / mss 齐了' : '缺 ' + (deps.missing || []).join(' / '),
  })
  const ff = await findFfmpeg()
  items.push({ key: 'ffmpeg', label: 'ffmpeg', ok: ff.ok, detail: ff.ok ? (ff.version || ff.path || '在') : '没找到（抓屏要用它）' })
  const ready = items.every((it) => it.ok)
  return {
    ready,
    items,
    hint: ready ? '都齐了，点右上角「打开」就能录。' : '点「一键准备」：能自动补的自己补，剩下按提示装。',
    python: py || '',
    venvDir: join(DSH_DIR, 'eye-venv'),
  }
}

/** 查 + 修：写路径、补依赖；Python/ffmpeg 装不了就给步骤 */
export async function prepare() {
  const steps = []
  const paths = readPaths()
  const dir = process.env.DSH_EYE_HOME || paths.dir || BUNDLED_PY
  const py = await findPython()

  // 1. 路径：写进 eye.json（安装器没跑过的话，这里补上）
  if (existsSync(join(dir, 'eye_serve.py'))) {
    try {
      const cfg = readCfg()
      const nextPaths = { ...(cfg.paths || {}), dir: dir.replace(/\\/g, '/') }
      if (py) nextPaths.python = py
      writeFileSync(EYE_JSON, JSON.stringify({ ...cfg, paths: nextPaths }, null, 2) + '\n', 'utf8')
      steps.push({ ok: true, text: '脚本路径已写进 ' + EYE_JSON })
    } catch (e) {
      steps.push({ ok: false, text: '写 ' + EYE_JSON + ' 失败：' + String((e && e.message) || e) })
    }
  } else {
    steps.push({ ok: false, text: '插件里没有 python 目录（' + BUNDLED_PY + '），重装一遍插件' })
  }

  // 2. Python 本身：装不了，只能告诉他去哪下
  if (!py) {
    steps.push({ ok: false, text: '没找到 Python 3。去 https://www.python.org/downloads/ 装 3.10 以上，安装第一页勾「Add python.exe to PATH」，装完回来再点一次。' })
  } else {
    const ver = await pythonVersion(py)
    steps.push({ ok: true, text: '用这个 Python：' + py + '（' + (ver || '?') + '）' })
    // 3. 依赖：直接 pip 装
    const deps = await missingDeps(py)
    if (deps.ok) {
      steps.push({ ok: true, text: '依赖已经齐了' })
    } else if (existsSync(REQ)) {
      steps.push({ ok: true, text: '开始装依赖：' + (deps.missing || []).join(' / ') + '（可能要一两分钟）' })
      const ins = await run(py, ['-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', REQ], 300000)
      if (ins.ok) {
        const again = await missingDeps(py)
        steps.push({ ok: again.ok, text: again.ok ? '依赖装好了' : '装完还有问题：' + (again.missing || []).join(' / ') + '（看下面的输出）' })
      } else {
        steps.push({ ok: false, text: 'pip 装失败（code ' + ins.code + '）：' + firstLine(ins.err || ins.out) 
          + '。多半是没网或被代理拦了；也可以手动跑：' + py + ' -m pip install -r ' + REQ })
      }
    } else {
      steps.push({ ok: false, text: '插件里缺 requirements.txt（' + REQ + '），重装一遍插件' })
    }
  }

  // 4. ffmpeg：winget 能装就装，装不了给下载地址
  const ff = await findFfmpeg()
  if (ff.ok) {
    steps.push({ ok: true, text: 'ffmpeg 在：' + (ff.version || ff.path) })
  } else {
    const wg = await run('winget', ['--version'], 8000)
    if (wg.ok) {
      steps.push({ ok: true, text: '开始装 ffmpeg（winget，几十秒）' })
      const ins = await run('winget', ['install', '--id', 'Gyan.FFmpeg', '-e', '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity'], 280000)
      const now = await findFfmpeg()
      steps.push({ ok: now.ok, text: now.ok ? 'ffmpeg 装好了（新开的窗口才认 PATH，DSH 重启一次）' : 'winget 装 ffmpeg 没成功（code ' + ins.code + '）：' + firstLine(ins.out || ins.err) })
    } else {
      steps.push({ ok: false, text: '没 ffmpeg，也没 winget。手动装：https://www.gyan.dev/ffmpeg/builds/ 下载 release-essentials，解压后把 bin 目录加到 PATH。' })
    }
  }

  const after = await check()
  return { ok: after.ready, steps, status: after }
}
// 本地克隆音色桥：把 voice-mini 的 kokoro 后端指向常驻的 F5-TTS HTTP 服务。
// 契约不变：<text> <out.wav> [voice] [speed]。voice 若是 F5 音色名则直用，
// 否则按 KOKORO_TO_CLONE 映射；未知一律取 KNOWN[0]。F5 不可达时回落到原脚本。
import { spawn } from 'node:child_process'
import { writeFile, unlink } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const [text, outFile, voice = 'af_heart', speedArg = '1'] = process.argv.slice(2)
if (!text || !outFile) {
  console.error('usage: synth-kokoro.mjs <text> <out.wav> [voice] [speed]')
  process.exit(2)
}

const HOST = process.env.F5_TTS_URL ?? 'http://127.0.0.1:18231'
const KNOWN = ['speaker_a', 'speaker_a_soft', 'speaker_a_hard', 'speaker_a_tease', 'speaker_a_shame', 'speaker_b']
const KOKORO_TO_CLONE = {
  af_heart: 'speaker_a',
  af_bella: 'speaker_a_soft',
  af_nicole: 'speaker_a_tease',
  af_sarah: 'speaker_a_shame',
  am_michael: 'speaker_a_hard',
  am_puck: 'speaker_a_tease',
}
const pick = KNOWN.includes(voice) ? voice : (KOKORO_TO_CLONE[voice] ?? KNOWN[0])
const speed = Number.parseFloat(speedArg)
const safeSpeed = Number.isFinite(speed) && speed > 0 ? Math.min(1.4, Math.max(0.7, speed)) : 1

async function viaF5() {
  const r = await fetch(`${HOST}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: pick, speed: safeSpeed, nfe: 32, cfg: 2.0 }),
    signal: AbortSignal.timeout(300_000),
  })
  if (!r.ok) throw new Error(`f5 http ${r.status}: ${(await r.text()).slice(0, 200)}`)
  const buf = Buffer.from(await r.arrayBuffer())
  if (buf.length < 200) throw new Error('f5 returned empty audio')
  await writeFile(outFile, buf)
  return buf.length
}

function viaLocalKokoro() {
  const script = join(dirname(fileURLToPath(import.meta.url)), 'synth-kokoro.local.mjs')
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, text, outFile, ...(voice ? [voice, String(safeSpeed)] : [])], {
      stdio: 'inherit',
    })
    child.on('error', reject)
    child.on('exit', () => (existsSync(outFile) ? resolve() : reject(new Error('local kokoro produced no audio'))))
  })
}

try {
  const bytes = await viaF5()
  if (process.env.DSH_VOICE_MINI_DEBUG) console.error(`[clone] ${pick} ${bytes}B ${text.slice(0, 24)}`)
} catch (error) {
  try {
    await unlink(outFile)
  } catch {}
  if (process.env.DSH_VOICE_MINI_DEBUG) console.error(`[clone] f5 failed (${error.message}), falling back to kokoro`)
  await viaLocalKokoro()
}
process.exit(0)

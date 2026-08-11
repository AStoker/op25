// Runs the SHIPPED PlaybackAgc/softKnee against the same signal the Python
// reference model uses, and prints stats in the same format so the two can be
// compared directly. Bundled with esbuild and run in Node.
import { PlaybackAgc, softKnee } from '../src/utils/audioAgc';

const RATE = 8000;
const FULL = 32768;

function speechLike(seconds = 6.0, rmsTarget = 0.045, peakTarget = 0.85): Float64Array {
  const n = Math.floor(RATE * seconds);
  const out = new Float64Array(n);
  const f0 = 120.0;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    let syl = Math.max(0, Math.sin(2 * Math.PI * 4.0 * t)) ** 1.5;
    if (t % 3.0 > 1.8) syl = 0;
    let v = 0;
    for (const [h, amp] of [[1, 1.0], [2, 0.6], [3, 0.35], [4, 0.18], [5, 0.09]]) {
      v += amp * Math.sin(2 * Math.PI * f0 * h * t);
    }
    const boost = Math.floor(t / 0.75) % 5 === 0 ? 2.6 : 1.0;
    out[i] = v * syl * boost;
  }
  let s = 0;
  for (const v of out) s += v * v;
  const curRms = Math.sqrt(s / n);
  for (let i = 0; i < n; i++) out[i] *= rmsTarget / curRms;
  let peak = 0;
  for (const v of out) peak = Math.max(peak, Math.abs(v));
  if (peak > peakTarget) for (let i = 0; i < n; i++) out[i] *= peakTarget / peak;
  return out;
}

/** Mirrors ha_bridge.speech_rms: mean RMS of the louder half of 20 ms frames. */
function speechRms(f: ArrayLike<number>): number {
  const n = Math.floor((RATE * 20) / 1000);
  const frames: number[] = [];
  for (let i = 0; i + n <= f.length; i += n) {
    let s = 0;
    for (let k = i; k < i + n; k++) {
      // Quantise to int16 first, as the Python does on real PCM.
      const q = Math.round(f[k] * FULL) / FULL;
      s += q * q;
    }
    frames.push(Math.sqrt(s / n));
  }
  frames.sort((a, b) => a - b);
  const loud = frames.slice(frames.length >> 1);
  return loud.reduce((a, b) => a + b, 0) / loud.length;
}

function flatRunPct(f: ArrayLike<number>, thresh = 0.995): number {
  const q = Array.from(f, (v) => Math.round(v * 1e4) / 1e4);
  let total = 0, i = 0;
  while (i < q.length) {
    let j = i;
    while (j + 1 < q.length && q[j + 1] === q[i]) j++;
    if (j - i + 1 >= 3 && Math.abs(q[i]) >= thresh) total += j - i + 1;
    i = j + 1;
  }
  return (total / q.length) * 100;
}

/** The same block loop useAudioStream runs, at 1:1 rate so it is comparable. */
function runShipped(src: Float64Array, blockMs = 120): Float64Array {
  const agc = new PlaybackAgc(blockMs, RATE);
  const nBlock = Math.floor((RATE * blockMs) / 1000);
  const out = new Float64Array(src.length);
  for (let start = 0; start < src.length; start += nBlock) {
    const upto = Math.min(src.length, start + nBlock);
    const gain = agc.observe(src as unknown as Float32Array, start, upto);
    for (let i = start; i < upto; i++) out[i] = softKnee(gain * src[i]);
  }
  return out;
}

let failures = 0;

function check(ok: boolean, label: string, detail = ''): void {
  console.log('%s %s%s', ok ? 'ok  ' : 'FAIL', label, detail ? '  ' + detail : '');
  if (!ok) failures++;
}

// --- the transfer function -------------------------------------------------
// Exactly linear below the knee: the old chain's defect was a nonlinearity that
// began at 0.25 of full scale, which is squarely inside normal speech.
for (const u of [0, 0.1, 0.35, 0.5, 0.699]) {
  check(Math.abs(softKnee(u) - u) < 1e-12, `softKnee(${u}) is linear`);
}
check(softKnee(0.7) === 0.7, 'softKnee is linear up to the knee');
// Asymptotic, never clamped flat: no input maps to exactly 1 until absurdly far
// past full scale, so peaks compress instead of squaring off.
check(softKnee(1.0) < 1 && softKnee(1.0) > 0.9, 'softKnee(1.0) compresses',
      softKnee(1.0).toFixed(4));
check(softKnee(2.0) < 1, 'softKnee(2.0) still below full scale', softKnee(2.0).toFixed(6));
let mono = true;
for (let u = 0; u < 4; u += 0.001) if (softKnee(u + 0.001) < softKnee(u)) mono = false;
check(mono, 'softKnee is monotonic');
check(softKnee(-0.85) === -softKnee(0.85), 'softKnee is odd-symmetric');

// --- levelling across the range the decoder actually produces --------------
// Live traffic spans ~28 dB of RMS between talkgroups. The old fixed 4x chain
// answered that with +8..+12 dB of over-drive and up to 6.2% of samples flat-
// topped; these bounds are what "consistent and clean" looks like instead.
console.log();
console.log('%s %s', 'input rms'.padEnd(10), 'speech rms / peak / flat-topped');
const levels: number[] = [];
for (const rms of [0.005, 0.015, 0.045, 0.12, 0.30]) {
  const y = runShipped(speechLike(6.0, rms, 0.98));
  let peak = 0;
  for (const v of y) peak = Math.max(peak, Math.abs(v));
  const srms = speechRms(y);
  const flat = flatRunPct(y);
  levels.push(srms);
  console.log('%s %s / %s / %s%%', rms.toFixed(3).padEnd(10), srms.toFixed(4),
              peak.toFixed(3), flat.toFixed(2).padStart(5));
  check(flat === 0, `no flat-topping at input rms ${rms}`);
  check(peak <= 1.0, `peak within full scale at input rms ${rms}`);
}
// Consistency is the whole point: a 60x spread of input must not survive as a
// large spread of output loudness.
const spreadDb = 20 * Math.log10(Math.max(...levels) / Math.min(...levels));
check(spreadDb < 6, 'output loudness spread stays under 6 dB', spreadDb.toFixed(1) + ' dB');
// ...and it must land near the clip normaliser's target (3000/32768), which is
// what makes live audio and the recording of the same call sound alike.
const target = 3_000 / 32_768;
for (const srms of levels.slice(1)) {
  const gap = 20 * Math.log10(srms / target);
  check(gap > -5 && gap < 2, 'within 5 dB of the clip target', gap.toFixed(1) + ' dB');
}

console.log();
console.log(failures ? `${failures} FAILURE(S)` : 'all checks passed');
process.exit(failures ? 1 : 0);

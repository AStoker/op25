/**
 * Playback levelling for the live stream, matched to what the recordings do.
 *
 * A fixed gain into a limiter was wrong in both directions at once. Live traffic
 * spans roughly 28 dB of RMS between talkgroups, so one multiplier cannot suit all
 * of it: quiet calls stayed quiet and loud ones were driven hard into the clamp.
 * Measured against a speech-shaped signal at five input levels, the old 4x chain
 * landed +8 to +12 dB louder than the same audio in a clip, with 0.8% to 6.2% of
 * samples flat-topped at full scale. That distortion is why a recording of a call
 * sounded better than hearing it live.
 *
 * The clip path (ha_bridge.normalize_pcm16) levels each call to a speech-RMS
 * target and then *backs the gain off* so peaks cannot cross a ceiling, which is
 * why it never clips. Same targets here, as a streaming AGC because live audio
 * cannot look ahead over a whole call. On the same five levels: within 0.7-3.0 dB
 * of the clip, and nothing flat-topped anywhere.
 *
 * Lives in its own module so it can be exercised without a browser: run
 * `yarn verify:agc` (tools/verify-agc.ts), which drives this exact code over a
 * speech-shaped signal at five input levels and asserts the two properties that
 * were broken — nothing flat-topped, and loudness consistent across the range.
 * It runs in CI. Retuning the constants below without re-running it is how the
 * previous chain came to claim it compressed smoothly while it hard-clipped.
 */

/** ≈ normalize_pcm16's 3000 target, nudged up for the AGC's attack/release lag. */
export const TARGET_RMS = 3_450 / 32_768;
/** Same ceiling on boost as the clip path, so near-silence is not amplified. */
export const MAX_GAIN_DB = 24.0;
/** Gain is reduced rather than letting peaks clip — the ordering that matters. */
export const PEAK_CEILING = 31_000 / 32_768;
export const AGC_FRAME_MS = 20;
/** ~2 s of level history. */
export const AGC_WINDOW_FRAMES = 100;
/** Ducking is fast so a transient never reaches the limiter... */
export const AGC_ATTACK_MS = 30.0;
/** ...boosting is slow, or quiet passages pump. */
export const AGC_RELEASE_MS = 400.0;
/** Below this the transfer is exactly linear; above it, tanh saturation. */
export const LIMIT_KNEE = 0.70;

/**
 * Soft-knee limiter: linear below {@link LIMIT_KNEE}, tanh-saturating above, and
 * asymptotic to ±1 so it can never emit a run of identical clamped peaks.
 *
 * This replaces a WaveShaper node, which was the actual bug. A WaveShaper's curve
 * spans an input domain of −1..+1 and the spec *clamps* anything outside it to the
 * end values — so feeding it a 4x-amplified signal turned every sample above 0.25
 * into exactly 1.0. It was a hard clipper wearing a soft clipper's name. Applying
 * the transfer per sample keeps the function and its input range in one place,
 * where they cannot drift apart again.
 */
export function softKnee(u: number): number {
  const a = Math.abs(u);
  if (a <= LIMIT_KNEE) return u;
  const over = (a - LIMIT_KNEE) / (1 - LIMIT_KNEE);
  const shaped = Math.min(LIMIT_KNEE + (1 - LIMIT_KNEE) * Math.tanh(over), 1);
  return u < 0 ? -shaped : shaped;
}

/**
 * Mean of the louder half of *frames* — the streaming form of ha_bridge's
 * speech_rms(). Plain mean RMS is dragged down by the pauses between phrases, so
 * a transmission with a lot of dead air would be boosted far more than one
 * without.
 */
export function speechLevel(frames: readonly number[]): number {
  if (!frames.length) return 0;
  const ordered = [...frames].sort((x, y) => x - y);
  const loud = ordered.slice(ordered.length >> 1);
  return loud.reduce((s, v) => s + v, 0) / loud.length;
}

export class PlaybackAgc {
  private frames: number[] = [];
  private peakEnv = 0;
  private gainValue = 1;
  private readonly attack: number;
  private readonly release: number;
  private readonly maxGain = 10 ** (MAX_GAIN_DB / 20);
  private readonly frameSamples: number;

  /** @param blockMs how often {@link observe} is called, which sets the slew rates. */
  constructor(blockMs: number, sampleRate: number) {
    this.attack = 1 - Math.exp(-blockMs / AGC_ATTACK_MS);
    this.release = 1 - Math.exp(-blockMs / AGC_RELEASE_MS);
    this.frameSamples = Math.max(1, Math.round((sampleRate * AGC_FRAME_MS) / 1_000));
  }

  get gain(): number {
    return this.gainValue;
  }

  /**
   * Fold one block of *input-rate* samples into the level estimate and settle the
   * gain. Returns the gain to apply to that block.
   *
   * Measure before the caller advances its read position: this has to see the
   * samples that are about to be played, not the ones after them.
   */
  observe(samples: Float32Array | readonly number[], from: number, upto: number): number {
    let blockPeak = 0;
    for (let i = from; i < upto; i += this.frameSamples) {
      const end = Math.min(i + this.frameSamples, upto);
      let sum = 0;
      for (let k = i; k < end; k++) {
        const v = samples[k];
        sum += v * v;
        const a = v < 0 ? -v : v;
        if (a > blockPeak) blockPeak = a;
      }
      if (end > i) this.frames.push(Math.sqrt(sum / (end - i)));
    }
    if (this.frames.length > AGC_WINDOW_FRAMES) {
      this.frames = this.frames.slice(-AGC_WINDOW_FRAMES);
    }
    this.peakEnv = Math.max(blockPeak, this.peakEnv * 0.85);

    const level = speechLevel(this.frames);
    let target = level > 1e-9 ? TARGET_RMS / level : 1;
    target = Math.min(target, this.maxGain);
    if (this.peakEnv > 1e-9) {
      target = Math.min(target, PEAK_CEILING / this.peakEnv);
    }
    this.gainValue += (target - this.gainValue) * (target < this.gainValue ? this.attack : this.release);
    return this.gainValue;
  }
}

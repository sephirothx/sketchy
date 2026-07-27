import { useSettingsStore } from "../store/settingsStore";

let audioCtx: AudioContext | null = null;

function unlockAudio() {
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", unlockAudio, { capture: true });
  window.addEventListener("keydown", unlockAudio, { capture: true });
  window.addEventListener("touchstart", unlockAudio, { capture: true });
  window.addEventListener("click", unlockAudio, { capture: true });
}

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) {
    const AudioCtxClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioCtxClass) {
      audioCtx = new AudioCtxClass();
    }
  }
  unlockAudio();
  return audioCtx;
}

function getVolumeGain(ctx: AudioContext): GainNode | null {
  const { soundEffects, volume } = useSettingsStore.getState();
  if (!soundEffects || volume <= 0) return null;

  const gain = ctx.createGain();
  // Scale overall sound volume smoothly
  gain.gain.value = Math.max(0, Math.min(1, volume * 0.4));
  gain.connect(ctx.destination);
  return gain;
}

/** Upbeat two-tone chime 🎉 (523Hz -> 659Hz) */
export function playCorrectGuessSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;

  // First note: C5 (523.25 Hz)
  const osc1 = ctx.createOscillator();
  const gain1 = ctx.createGain();
  osc1.type = "sine";
  osc1.frequency.setValueAtTime(523.25, now);
  gain1.gain.setValueAtTime(0.8, now);
  gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
  osc1.connect(gain1);
  gain1.connect(masterGain);
  osc1.start(now);
  osc1.stop(now + 0.15);

  // Second note: E5 (659.25 Hz)
  const osc2 = ctx.createOscillator();
  const gain2 = ctx.createGain();
  osc2.type = "triangle";
  osc2.frequency.setValueAtTime(659.25, now + 0.1);
  gain2.gain.setValueAtTime(1.0, now + 0.1);
  gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
  osc2.connect(gain2);
  gain2.connect(masterGain);
  osc2.start(now + 0.1);
  osc2.stop(now + 0.35);
}

/** Soft notification pop for close guess hints */
export function playCloseGuessSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(440, now);
  gain.gain.setValueAtTime(0.5, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);

  osc.connect(gain);
  gain.connect(masterGain);
  osc.start(now);
  osc.stop(now + 0.08);
}

/** Light bell / chord for round start 🎨 */
export function playRoundStartSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;
  const frequencies = [440, 554.37, 659.25]; // A4, C#5, E5

  frequencies.forEach((freq, idx) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const startTime = now + idx * 0.06;

    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, startTime);
    gain.gain.setValueAtTime(0.6, startTime);
    gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.3);

    osc.connect(gain);
    gain.connect(masterGain);
    osc.start(startTime);
    osc.stop(startTime + 0.3);
  });
}

/** Soft rising pitch blip for player joining 👥 */
export function playPlayerJoinSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(320, now);
  osc.frequency.exponentialRampToValueAtTime(540, now + 0.08);
  gain.gain.setValueAtTime(0.4, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);

  osc.connect(gain);
  gain.connect(masterGain);
  osc.start(now);
  osc.stop(now + 0.08);
}

/** Soft falling pitch blip for player leaving 👥 */
export function playPlayerLeaveSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(540, now);
  osc.frequency.exponentialRampToValueAtTime(320, now + 0.08);
  gain.gain.setValueAtTime(0.4, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);

  osc.connect(gain);
  gain.connect(masterGain);
  osc.start(now);
  osc.stop(now + 0.08);
}

/** Subtle tick during final 10 seconds ⏰ */
export function playTimerTickSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  const masterGain = getVolumeGain(ctx);
  if (!masterGain) return;

  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(800, now);
  gain.gain.setValueAtTime(0.3, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.02);

  osc.connect(gain);
  gain.connect(masterGain);
  osc.start(now);
  osc.stop(now + 0.02);
}

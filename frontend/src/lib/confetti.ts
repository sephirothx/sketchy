export function triggerConfettiBurst() {
  window.dispatchEvent(new CustomEvent("sketchy:confetti", { detail: { mode: "burst" } }));
}

export function triggerConfettiShower() {
  window.dispatchEvent(new CustomEvent("sketchy:confetti", { detail: { mode: "shower" } }));
}

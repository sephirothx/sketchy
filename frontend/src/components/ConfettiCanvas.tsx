import { useEffect, useRef } from "react";
import { useSettingsStore } from "../store/settingsStore";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  rotation: number;
  rotationSpeed: number;
  opacity: number;
  shape: "rect" | "circle";
}

const CONFETTI_COLORS = [
  "#ef4444",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#84cc16",
  "#eab308",
  "#f43f5e",
];

export function ConfettiCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const confettiEffects = useSettingsStore((s) => s.confettiEffects);

  useEffect(() => {
    if (!confettiEffects) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let particles: Particle[] = [];
    let animId: number | null = null;

    function resize() {
      if (canvas) {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
      }
    }
    resize();
    window.addEventListener("resize", resize);

    function addParticles(mode: "burst" | "shower") {
      const width = canvas?.width ?? window.innerWidth;
      const height = canvas?.height ?? window.innerHeight;
      const count = mode === "burst" ? 70 : 180;

      for (let i = 0; i < count; i++) {
        const color = CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)];
        const shape: "rect" | "circle" = Math.random() > 0.3 ? "rect" : "circle";
        const size = Math.random() * 8 + 6;

        if (mode === "burst") {
          const startX = width * (0.2 + Math.random() * 0.6);
          const startY = height * (0.5 + Math.random() * 0.3);
          particles.push({
            x: startX,
            y: startY,
            vx: (Math.random() - 0.5) * 12,
            vy: -Math.random() * 10 - 4,
            size,
            color,
            rotation: Math.random() * Math.PI * 2,
            rotationSpeed: (Math.random() - 0.5) * 0.2,
            opacity: 1,
            shape,
          });
        } else {
          particles.push({
            x: Math.random() * width,
            y: -Math.random() * height * 0.4,
            vx: (Math.random() - 0.5) * 3,
            vy: Math.random() * 3 + 1,
            size,
            color,
            rotation: Math.random() * Math.PI * 2,
            rotationSpeed: (Math.random() - 0.5) * 0.15,
            opacity: 1,
            shape,
          });
        }
      }

      if (!animId) {
        animId = requestAnimationFrame(loop);
      }
    }

    function loop() {
      if (!canvas || !ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const gravity = 0.16;
      const drag = 0.98;

      particles.forEach((p) => {
        p.vx *= drag;
        p.vy = (p.vy + gravity) * drag;
        p.x += p.vx;
        p.y += p.vy;
        p.rotation += p.rotationSpeed;
        p.opacity -= 0.004;

        if (p.opacity <= 0) return;

        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rotation);
        ctx.globalAlpha = Math.max(0, p.opacity);
        ctx.fillStyle = p.color;

        if (p.shape === "rect") {
          ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        } else {
          ctx.beginPath();
          ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
          ctx.fill();
        }

        ctx.restore();
      });

      particles = particles.filter((p) => p.opacity > 0 && p.y < canvas.height + 50);

      if (particles.length > 0) {
        animId = requestAnimationFrame(loop);
      } else {
        animId = null;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    }

    function handleConfettiEvent(e: Event) {
      const customEv = e as CustomEvent<{ mode: "burst" | "shower" }>;
      addParticles(customEv.detail?.mode ?? "burst");
    }

    window.addEventListener("sketchy:confetti", handleConfettiEvent);
    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("sketchy:confetti", handleConfettiEvent);
      if (animId) cancelAnimationFrame(animId);
    };
  }, [confettiEffects]);

  if (!confettiEffects) return null;

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
        zIndex: 9999,
      }}
    />
  );
}

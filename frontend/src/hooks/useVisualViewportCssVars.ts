import { useEffect } from "react";

/**
 * Keeps CSS custom properties on :root in sync with window.visualViewport
 * so layout can size to the visible area (including soft-keyboard shrink)
 * without imperative element.style writes.
 */
export function useVisualViewportCssVars() {
  useEffect(() => {
    const root = document.documentElement;

    function update() {
      const vv = window.visualViewport;
      if (vv) {
        root.style.setProperty("--vv-height", `${vv.height}px`);
        root.style.setProperty("--vv-width", `${vv.width}px`);
        root.style.setProperty("--vv-offset-top", `${vv.offsetTop}px`);
        root.style.setProperty("--vv-offset-left", `${vv.offsetLeft}px`);
        root.style.setProperty("--app-height", `${vv.height}px`);
      } else {
        root.style.setProperty("--vv-height", `${window.innerHeight}px`);
        root.style.setProperty("--vv-width", `${window.innerWidth}px`);
        root.style.setProperty("--vv-offset-top", "0px");
        root.style.setProperty("--vv-offset-left", "0px");
        root.style.setProperty("--app-height", "100dvh");
      }
    }

    update();
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      window.visualViewport?.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);
}

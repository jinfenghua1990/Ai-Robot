import { useEffect, useState } from "react";

function getThemeFromUrl(): "light" | "dark" | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const t = params.get("theme");
  if (t === "light" || t === "dark") return t;
  return null;
}

function getInitialTheme(): boolean {
  const fromUrl = getThemeFromUrl();
  if (fromUrl) return fromUrl === "dark";
  const saved = localStorage.getItem("vr-theme");
  if (saved) return saved === "dark";
  return false; // 默认亮色，与 AIROBOT 一致
}

// 接入 AIROBOT：默认与 AIROBAT 保持一致走亮色，用户可切暗色，选择存 localStorage。
// 支持通过 URL ?theme=light|dark 指定初始主题，也支持父页面 postMessage 实时同步。
export function useDarkMode() {
  const [dark, setDark] = useState(() => getInitialTheme());

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.remove("light"); // 兼容旧类名
    localStorage.setItem("vr-theme", dark ? "dark" : "light");
  }, [dark]);

  // 监听 AIROBOT 父页面主题同步
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      if (e.data?.type === "airobot-theme") {
        const next = e.data.theme === "dark";
        setDark(next);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  return { dark, toggle: () => setDark((d) => !d) };
}

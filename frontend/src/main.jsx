import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// ---- 构建自愈 ----
// 本地 uvicorn 用 immutable 缓存前端资源，重建（rm -rf dist）会删除旧 chunk。
// 浏览器若仍持有旧 bundle，懒加载旧 chunk 会 404 导致页面崩溃。
// 这里捕获动态导入失败并自动硬刷新一次，拉取最新构建。
function trySelfRecover() {
  let n = 0
  try { n = parseInt(sessionStorage.getItem('airobot_recover') || '0', 10) } catch (e) {}
  if (n >= 3) return // 防止极端情况下死循环
  try { sessionStorage.setItem('airobot_recover', String(n + 1)) } catch (e) {}
  window.location.replace(window.location.href)
}
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason
  const msg = (reason && reason.message) ? reason.message : String(reason)
  if (/Failed to fetch dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk|Failed to load|404/i.test(msg)) {
    trySelfRecover()
  }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// 标记已成功挂载，供 index.html 看门狗判断是否空白；并清除自愈计数器
window.__AIROBOT_BOOTED = true
try { sessionStorage.removeItem('airobot_recover') } catch (e) {}

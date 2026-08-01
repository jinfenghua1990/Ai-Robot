import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 构建版本号：每次构建时基于时间戳生成，强制浏览器拉新版本（破坏缓存）
const BUILD_VERSION = Date.now()

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        // 在 hash 后追加版本号前缀，确保内容变更后 hash 必变
        entryFileNames: `assets/[name].[hash].${BUILD_VERSION}.js`,
        chunkFileNames: `assets/[name].[hash].${BUILD_VERSION}.js`,
        assetFileNames: `assets/[name].[hash][extname]`,
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'echarts-vendor': ['echarts', 'echarts-for-react'],
          'charts-vendor': ['lightweight-charts'],
        }
      }
    }
  }
})

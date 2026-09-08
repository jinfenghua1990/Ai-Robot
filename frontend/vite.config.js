import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    host: '127.0.0.1',
    strictPort: true,
    allowedHosts: ['localhost', '127.0.0.1'],
    proxy: {
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rolldownOptions: {
      output: {
        // Vite 内容哈希已能精确失效缓存，避免每次构建让全部 chunk 无条件换名。
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: `assets/[name].[hash][extname]`,
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return undefined
          if (/\/node_modules\/(react|react-dom|react-router|react-router-dom)\//.test(id)) return 'react-vendor'
          if (/\/node_modules\/echarts\/lib\/chart\/(graph|sankey)\//.test(id)) return 'echarts-network-charts'
          if (/\/node_modules\/echarts\/lib\/chart\/(bar|candlestick)\//.test(id)) return 'echarts-bar-charts'
          if (id.includes('/node_modules/echarts/lib/chart/line/')) return 'echarts-line-chart'
          if (/\/node_modules\/echarts\/lib\/chart\/(scatter|effectScatter)\//.test(id)) return 'echarts-scatter-charts'
          if (/\/node_modules\/echarts\/lib\/chart\/(pie|radar)\//.test(id)) return 'echarts-radial-charts'
          if (id.includes('/node_modules/echarts/lib/chart/')) return 'echarts-chart-common'
          if (id.includes('/node_modules/echarts/lib/component/')) return 'echarts-components'
          if (id.includes('/node_modules/zrender/')) return 'echarts-renderer'
          if (id.includes('/node_modules/echarts-for-react/')) return 'echarts-react'
          if (id.includes('/node_modules/echarts/')) return 'echarts-core'
          if (id.includes('/node_modules/lightweight-charts/')) return 'charts-vendor'
          return undefined
        },
      }
    }
  }
})

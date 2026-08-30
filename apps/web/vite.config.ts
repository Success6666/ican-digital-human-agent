import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const agentTarget = env.VITE_AUTH_TARGET ?? 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT ?? 5173),
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: agentTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})

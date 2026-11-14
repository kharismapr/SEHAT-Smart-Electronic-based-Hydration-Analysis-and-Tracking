import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * Vite plugin that automatically launches the SEHAT backend server (port 5000)
 * during `npm run dev` if it is not already running.
 */
function sehatBackendAutoStart() {
  let backendProc = null
  return {
    name: 'sehat-backend-autostart',
    configureServer() {
      fetch('http://localhost:5000/api/health')
        .then((res) => {
          if (res.ok) {
            console.log('[SEHAT] Backend server already active on http://localhost:5000')
          }
        })
        .catch(() => {
          const serverDir = path.resolve(__dirname, '..', 'server')
          console.log('[SEHAT] Auto-starting SEHAT Backend Server on http://localhost:5000...')
          backendProc = spawn('node', ['server.js'], {
            cwd: serverDir,
            stdio: 'inherit',
            windowsHide: true
          })
        })

      process.on('exit', () => {
        if (backendProc) {
          try {
            backendProc.kill()
          } catch {
            // ignore
          }
        }
      })
    }
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    sehatBackendAutoStart(),
  ],
})

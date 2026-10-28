import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()], clearScreen: false, build: { target: 'es2022' },
  server: { watch: { ignored: ['**/src-tauri/**', '**/output/**', '**/output*.log', '**/tools/**'] } },
});

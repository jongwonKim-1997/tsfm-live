import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: process.env.TSFM_PUBLIC_ORIGIN || 'http://localhost:4321',
  output: 'static',
  ...(process.env.TSFM_PUBLIC_DIR ? {publicDir: process.env.TSFM_PUBLIC_DIR} : {}),
  ...(process.env.TSFM_SITE_OUTDIR ? {outDir: process.env.TSFM_SITE_OUTDIR} : {}),
  vite: { plugins: [tailwindcss()] },
  i18n: { defaultLocale: 'en', locales: ['en','ko'], routing: { prefixDefaultLocale: false } },
});

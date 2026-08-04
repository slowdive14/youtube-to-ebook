// @ts-check
import { defineConfig } from 'astro/config';
import vercel from '@astrojs/vercel';
import rehypeCollapsibleSections from './src/plugins/rehype-collapsible-sections.mjs';

// https://astro.build/config
export default defineConfig({
  // Public origin. On Vercel the SSR request URL resolves to localhost, so
  // anything building an absolute link (e.g. /api/reading) must use this.
  site: 'https://youtube-to-ebook-seven.vercel.app',
  output: 'static',
  adapter: vercel(),
  markdown: {
    // Summary-first reading: each section collapses behind its summary line.
    rehypePlugins: [rehypeCollapsibleSections],
  },
});

// @ts-check
import { defineConfig } from 'astro/config';
import vercel from '@astrojs/vercel';
import rehypeCollapsibleSections from './src/plugins/rehype-collapsible-sections.mjs';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  adapter: vercel(),
  markdown: {
    // Summary-first reading: each section collapses behind its summary line.
    rehypePlugins: [rehypeCollapsibleSections],
  },
});

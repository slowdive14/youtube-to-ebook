import { renderers } from './renderers.mjs';
import { c as createExports, s as serverEntrypointModule } from './chunks/_@astrojs-ssr-adapter_DKKWKRHR.mjs';
import { manifest } from './manifest_BIptZ1bJ.mjs';

const serverIslandMap = new Map();;

const _page0 = () => import('./pages/_image.astro.mjs');
const _page1 = () => import('./pages/api/define.astro.mjs');
const _page2 = () => import('./pages/drill/_---slug_.astro.mjs');
const _page3 = () => import('./pages/issues/_slug_/read.astro.mjs');
const _page4 = () => import('./pages/issues/_---slug_.astro.mjs');
const _page5 = () => import('./pages/index.astro.mjs');
const pageMap = new Map([
    ["node_modules/astro/dist/assets/endpoint/generic.js", _page0],
    ["src/pages/api/define.ts", _page1],
    ["src/pages/drill/[...slug].astro", _page2],
    ["src/pages/issues/[slug]/read.astro", _page3],
    ["src/pages/issues/[...slug].astro", _page4],
    ["src/pages/index.astro", _page5]
]);

const _manifest = Object.assign(manifest, {
    pageMap,
    serverIslandMap,
    renderers,
    actions: () => import('./noop-entrypoint.mjs'),
    middleware: () => import('./_noop-middleware.mjs')
});
const _args = {
    "middlewareSecret": "5c285b8d-0965-4efd-aa3e-dfb0c2da5605",
    "skewProtection": false
};
const _exports = createExports(_manifest, _args);
const __astrojsSsrVirtualEntry = _exports.default;
const _start = 'start';
if (Object.prototype.hasOwnProperty.call(serverEntrypointModule, _start)) ;

export { __astrojsSsrVirtualEntry as default, pageMap };

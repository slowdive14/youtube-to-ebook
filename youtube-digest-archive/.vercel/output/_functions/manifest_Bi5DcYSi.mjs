import 'piccolore';
import { l as decodeKey } from './chunks/astro/server_C9m0SROy.mjs';
import 'clsx';
import { N as NOOP_MIDDLEWARE_FN } from './chunks/astro-designed-error-pages_CcAV9U-v.mjs';
import 'es-module-lexer';

function sanitizeParams(params) {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => {
      if (typeof value === "string") {
        return [key, value.normalize().replace(/#/g, "%23").replace(/\?/g, "%3F")];
      }
      return [key, value];
    })
  );
}
function getParameter(part, params) {
  if (part.spread) {
    return params[part.content.slice(3)] || "";
  }
  if (part.dynamic) {
    if (!params[part.content]) {
      throw new TypeError(`Missing parameter: ${part.content}`);
    }
    return params[part.content];
  }
  return part.content.normalize().replace(/\?/g, "%3F").replace(/#/g, "%23").replace(/%5B/g, "[").replace(/%5D/g, "]");
}
function getSegment(segment, params) {
  const segmentPath = segment.map((part) => getParameter(part, params)).join("");
  return segmentPath ? "/" + segmentPath : "";
}
function getRouteGenerator(segments, addTrailingSlash) {
  return (params) => {
    const sanitizedParams = sanitizeParams(params);
    let trailing = "";
    if (addTrailingSlash === "always" && segments.length) {
      trailing = "/";
    }
    const path = segments.map((segment) => getSegment(segment, sanitizedParams)).join("") + trailing;
    return path || "/";
  };
}

function deserializeRouteData(rawRouteData) {
  return {
    route: rawRouteData.route,
    type: rawRouteData.type,
    pattern: new RegExp(rawRouteData.pattern),
    params: rawRouteData.params,
    component: rawRouteData.component,
    generate: getRouteGenerator(rawRouteData.segments, rawRouteData._meta.trailingSlash),
    pathname: rawRouteData.pathname || void 0,
    segments: rawRouteData.segments,
    prerender: rawRouteData.prerender,
    redirect: rawRouteData.redirect,
    redirectRoute: rawRouteData.redirectRoute ? deserializeRouteData(rawRouteData.redirectRoute) : void 0,
    fallbackRoutes: rawRouteData.fallbackRoutes.map((fallback) => {
      return deserializeRouteData(fallback);
    }),
    isIndex: rawRouteData.isIndex,
    origin: rawRouteData.origin
  };
}

function deserializeManifest(serializedManifest) {
  const routes = [];
  for (const serializedRoute of serializedManifest.routes) {
    routes.push({
      ...serializedRoute,
      routeData: deserializeRouteData(serializedRoute.routeData)
    });
    const route = serializedRoute;
    route.routeData = deserializeRouteData(serializedRoute.routeData);
  }
  const assets = new Set(serializedManifest.assets);
  const componentMetadata = new Map(serializedManifest.componentMetadata);
  const inlinedScripts = new Map(serializedManifest.inlinedScripts);
  const clientDirectives = new Map(serializedManifest.clientDirectives);
  const serverIslandNameMap = new Map(serializedManifest.serverIslandNameMap);
  const key = decodeKey(serializedManifest.key);
  return {
    // in case user middleware exists, this no-op middleware will be reassigned (see plugin-ssr.ts)
    middleware() {
      return { onRequest: NOOP_MIDDLEWARE_FN };
    },
    ...serializedManifest,
    assets,
    componentMetadata,
    inlinedScripts,
    clientDirectives,
    routes,
    serverIslandNameMap,
    key
  };
}

const manifest = deserializeManifest({"hrefRoot":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/","cacheDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/node_modules/.astro/","outDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/dist/","srcDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/","publicDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/public/","buildClientDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/dist/client/","buildServerDir":"file:///C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/dist/server/","adapterName":"@astrojs/vercel","routes":[{"file":"","links":[],"scripts":[],"styles":[],"routeData":{"type":"page","component":"_server-islands.astro","params":["name"],"segments":[[{"content":"_server-islands","dynamic":false,"spread":false}],[{"content":"name","dynamic":true,"spread":false}]],"pattern":"^\\/_server-islands\\/([^/]+?)\\/?$","prerender":false,"isIndex":false,"fallbackRoutes":[],"route":"/_server-islands/[name]","origin":"internal","_meta":{"trailingSlash":"ignore"}}},{"file":"index.html","links":[],"scripts":[],"styles":[],"routeData":{"route":"/","isIndex":true,"type":"page","pattern":"^\\/$","segments":[],"params":[],"component":"src/pages/index.astro","pathname":"/","prerender":true,"fallbackRoutes":[],"distURL":[],"origin":"project","_meta":{"trailingSlash":"ignore"}}},{"file":"","links":[],"scripts":[],"styles":[],"routeData":{"type":"endpoint","isIndex":false,"route":"/_image","pattern":"^\\/_image\\/?$","segments":[[{"content":"_image","dynamic":false,"spread":false}]],"params":[],"component":"node_modules/astro/dist/assets/endpoint/generic.js","pathname":"/_image","prerender":false,"fallbackRoutes":[],"origin":"internal","_meta":{"trailingSlash":"ignore"}}},{"file":"","links":[],"scripts":[],"styles":[],"routeData":{"route":"/api/define","isIndex":false,"type":"endpoint","pattern":"^\\/api\\/define\\/?$","segments":[[{"content":"api","dynamic":false,"spread":false}],[{"content":"define","dynamic":false,"spread":false}]],"params":[],"component":"src/pages/api/define.ts","pathname":"/api/define","prerender":false,"fallbackRoutes":[],"distURL":[],"origin":"project","_meta":{"trailingSlash":"ignore"}}}],"base":"/","trailingSlash":"ignore","compressHTML":true,"componentMetadata":[["\u0000astro:content",{"propagation":"in-tree","containsHead":false}],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/drill/[...slug].astro",{"propagation":"in-tree","containsHead":true}],["\u0000@astro-page:src/pages/drill/[...slug]@_@astro",{"propagation":"in-tree","containsHead":false}],["\u0000@astrojs-ssr-virtual-entry",{"propagation":"in-tree","containsHead":false}],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/index.astro",{"propagation":"in-tree","containsHead":true}],["\u0000@astro-page:src/pages/index@_@astro",{"propagation":"in-tree","containsHead":false}],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro",{"propagation":"in-tree","containsHead":true}],["\u0000@astro-page:src/pages/issues/[...slug]@_@astro",{"propagation":"in-tree","containsHead":false}]],"renderers":[],"clientDirectives":[["idle","(()=>{var l=(n,t)=>{let i=async()=>{await(await n())()},e=typeof t.value==\"object\"?t.value:void 0,s={timeout:e==null?void 0:e.timeout};\"requestIdleCallback\"in window?window.requestIdleCallback(i,s):setTimeout(i,s.timeout||200)};(self.Astro||(self.Astro={})).idle=l;window.dispatchEvent(new Event(\"astro:idle\"));})();"],["load","(()=>{var e=async t=>{await(await t())()};(self.Astro||(self.Astro={})).load=e;window.dispatchEvent(new Event(\"astro:load\"));})();"],["media","(()=>{var n=(a,t)=>{let i=async()=>{await(await a())()};if(t.value){let e=matchMedia(t.value);e.matches?i():e.addEventListener(\"change\",i,{once:!0})}};(self.Astro||(self.Astro={})).media=n;window.dispatchEvent(new Event(\"astro:media\"));})();"],["only","(()=>{var e=async t=>{await(await t())()};(self.Astro||(self.Astro={})).only=e;window.dispatchEvent(new Event(\"astro:only\"));})();"],["visible","(()=>{var a=(s,i,o)=>{let r=async()=>{await(await s())()},t=typeof i.value==\"object\"?i.value:void 0,c={rootMargin:t==null?void 0:t.rootMargin},n=new IntersectionObserver(e=>{for(let l of e)if(l.isIntersecting){n.disconnect(),r();break}},c);for(let e of o.children)n.observe(e)};(self.Astro||(self.Astro={})).visible=a;window.dispatchEvent(new Event(\"astro:visible\"));})();"]],"entryModules":{"\u0000noop-middleware":"_noop-middleware.mjs","\u0000virtual:astro:actions/noop-entrypoint":"noop-entrypoint.mjs","\u0000@astro-page:node_modules/astro/dist/assets/endpoint/generic@_@js":"pages/_image.astro.mjs","\u0000@astro-page:src/pages/api/define@_@ts":"pages/api/define.astro.mjs","\u0000@astro-page:src/pages/drill/[...slug]@_@astro":"pages/drill/_---slug_.astro.mjs","\u0000@astro-page:src/pages/issues/[...slug]@_@astro":"pages/issues/_---slug_.astro.mjs","\u0000@astro-page:src/pages/index@_@astro":"pages/index.astro.mjs","\u0000@astrojs-ssr-virtual-entry":"entry.mjs","\u0000@astro-renderers":"renderers.mjs","\u0000@astrojs-ssr-adapter":"_@astrojs-ssr-adapter.mjs","\u0000@astrojs-manifest":"manifest_Bi5DcYSi.mjs","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/node_modules/astro/dist/assets/services/sharp.js":"chunks/sharp_DvEbSuwK.mjs","C:\\Users\\user\\Downloads\\youtube-to-ebook\\youtube-digest-archive\\.astro\\content-assets.mjs":"chunks/content-assets_DleWbedO.mjs","C:\\Users\\user\\Downloads\\youtube-to-ebook\\youtube-digest-archive\\.astro\\content-modules.mjs":"chunks/content-modules_Dz-S_Wwv.mjs","\u0000astro:data-layer-content":"chunks/_astro_data-layer-content_D2SCiHzc.mjs","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/drill/[...slug].astro?astro&type=script&index=0&lang.ts":"_astro/_...slug_.astro_astro_type_script_index_0_lang.CnK7EDOI.js","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/index.astro?astro&type=script&index=0&lang.ts":"_astro/index.astro_astro_type_script_index_0_lang.Cs48PcAv.js","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=0&lang.ts":"_astro/_...slug_.astro_astro_type_script_index_0_lang.CWk-O_DW.js","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=1&lang.ts":"_astro/_...slug_.astro_astro_type_script_index_1_lang.CJkItEj4.js","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=2&lang.ts":"_astro/_...slug_.astro_astro_type_script_index_2_lang.DmpzLe3R.js","C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=3&lang.ts":"_astro/_...slug_.astro_astro_type_script_index_3_lang.DbIruryY.js","astro:scripts/before-hydration.js":""},"inlinedScripts":[["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/index.astro?astro&type=script&index=0&lang.ts","document.addEventListener(\"DOMContentLoaded\",()=>{const h=\"yt-digest-read-issues\",p=\"yt-digest-sub-progress\";function o(){try{return new Set(JSON.parse(localStorage.getItem(h)||\"[]\"))}catch{return new Set}}function n(e){localStorage.setItem(h,JSON.stringify([...e]))}function S(){try{return JSON.parse(localStorage.getItem(p)||\"{}\")}catch{return{}}}function f(e){localStorage.setItem(p,JSON.stringify(e))}function u(){const e=document.querySelectorAll(\".issue-card-wrapper\").length,t=document.querySelectorAll(\".issue-card-wrapper.is-read\").length,s=document.getElementById(\"read-stats\");s&&(s.textContent=`${t} / ${e} read`)}function y(){const e=S();document.querySelectorAll(\".sub-checks\").forEach(t=>{const s=t.dataset.issueId,c=e[s]||{};t.querySelectorAll(\".sub-check-btn\").forEach(d=>{const i=d.dataset.type;c[i]?d.classList.add(\"checked\"):d.classList.remove(\"checked\")});const r=t.querySelectorAll(\".sub-check-btn\"),a=t.querySelectorAll(\".sub-check-btn.checked\"),l=t.closest(\".issue-card-wrapper\");if(r.length>0&&r.length===a.length){l.classList.add(\"is-read\");const d=o();d.add(s),n(d)}})}const k=o();document.querySelectorAll(\".issue-card-wrapper\").forEach(e=>{const t=e.dataset.issueId;k.has(t)&&e.classList.add(\"is-read\")}),y(),u(),document.querySelectorAll(\".read-check\").forEach(e=>{e.addEventListener(\"click\",t=>{t.preventDefault(),t.stopPropagation();const s=e.dataset.issueId,c=e.closest(\".issue-card-wrapper\"),r=o();r.has(s)?(r.delete(s),c.classList.remove(\"is-read\")):(r.add(s),c.classList.add(\"is-read\")),n(r),u()})}),document.querySelectorAll(\".sub-check-btn\").forEach(e=>{e.addEventListener(\"click\",t=>{t.preventDefault(),t.stopPropagation();const s=e.closest(\".sub-checks\"),c=s.dataset.issueId,r=e.dataset.type,a=S();a[c]||(a[c]={}),a[c][r]?(delete a[c][r],e.classList.remove(\"checked\")):(a[c][r]=!0,e.classList.add(\"checked\")),f(a);const l=s.querySelectorAll(\".sub-check-btn\"),d=s.querySelectorAll(\".sub-check-btn.checked\"),i=s.closest(\".issue-card-wrapper\"),g=o();l.length>0&&l.length===d.length&&(i.classList.add(\"is-read\"),g.add(c)),n(g),u()})})});"],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=0&lang.ts","document.addEventListener(\"DOMContentLoaded\",()=>{const u=document.querySelector(\".markdown-content\");if(!u)return;const e=document.getElementById(\"dict-trigger\"),n=document.getElementById(\"dict-popup\"),w=document.getElementById(\"dict-popup-word\"),a=document.getElementById(\"dict-popup-body\"),y=document.getElementById(\"dict-popup-close\");if(!e||!n||!w||!a||!y)return;let o=\"\",d=null,p=!1;function l(){e.hidden=!0,d&&(clearTimeout(d),d=null)}function g(){const t=window.getSelection();if(!t||t.isCollapsed||!t.toString().trim()||!n.hidden)return;const i=t.toString().trim();if(!u.contains(t.anchorNode)||i.length>500||i.length<1)return;o=i;const r=t.getRangeAt(0).getBoundingClientRect();e.hidden=!1,e.style.top=r.bottom+window.scrollY+8+\"px\",e.style.left=Math.min(r.left+r.width/2-30,window.innerWidth-80)+\"px\",d&&clearTimeout(d),d=setTimeout(l,5e3)}u.addEventListener(\"mouseup\",()=>setTimeout(g,50)),u.addEventListener(\"touchend\",()=>setTimeout(g,50));let m=null;document.addEventListener(\"selectionchange\",()=>{m&&clearTimeout(m),m=setTimeout(g,300)}),document.addEventListener(\"scroll\",()=>{p||l()},{passive:!0}),document.addEventListener(\"touchstart\",t=>{e.contains(t.target)?p=!0:l()},{passive:!0}),document.addEventListener(\"touchend\",()=>{p=!1},{passive:!0}),document.addEventListener(\"touchcancel\",()=>{p=!1},{passive:!0});function E(t){if(!t.anchorNode)return\"\";const i=t.anchorNode.parentElement?.closest(\"p, li, blockquote, h1, h2, h3\");if(!i)return\"\";const s=i.textContent||\"\";return s.length>300?s.substring(0,300)+\"...\":s}e.addEventListener(\"click\",async t=>{if(t.preventDefault(),t.stopPropagation(),!o)return;const i=window.getSelection(),s=i?E(i):\"\",r=e.getBoundingClientRect();n.hidden=!1,n.style.top=r.bottom+window.scrollY+8+\"px\",n.style.left=Math.max(8,Math.min(r.left+r.width/2-160,window.innerWidth-328))+\"px\";const T=o.length>40?o.substring(0,40)+\"...\":o;w.textContent=T,a.innerHTML='<div class=\"dict-loading\"><span class=\"dict-spinner\"></span> 검색 중...</div>',l();try{const f=await fetch(\"/api/define\",{method:\"POST\",headers:{\"Content-Type\":\"application/json\"},body:JSON.stringify({text:o,context:s})});if(!f.ok){const c=await f.json();a.textContent=c.error||\"오류가 발생했습니다\";return}const x=(await f.json()).result.split(`\n`).filter(c=>c.trim());a.innerHTML=x.map(c=>{const v=c.match(/^\\[(.+?)\\]\\s*(.+)/);return v?`<div class=\"dict-entry\"><span class=\"dict-label\">${v[1]}</span> ${v[2]}</div>`:`<div class=\"dict-entry\">${c}</div>`}).join(\"\")}catch{a.textContent=\"네트워크 오류. 다시 시도해주세요.\"}});function h(){n.hidden=!0,l(),o=\"\",window.getSelection()?.removeAllRanges()}y.addEventListener(\"click\",h),document.addEventListener(\"click\",t=>{!n.hidden&&!n.contains(t.target)&&t.target!==e&&!e.contains(t.target)&&h()}),document.addEventListener(\"keydown\",t=>{t.key===\"Escape\"&&!n.hidden&&h()})});"],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=2&lang.ts","document.addEventListener(\"DOMContentLoaded\",()=>{const r=document.querySelector(\".markdown-content\");if(!r)return;const a=Array.from(r.children);let s=-1,c=-1;if(a.forEach((e,t)=>{if(e.tagName===\"H2\"){const n=e.textContent.trim();/^English$/i.test(n)?s=t:/^한국어$/i.test(n)&&(c=t)}}),s===-1)return;const l=c!==-1?c:a.length,i=document.createElement(\"section\");i.setAttribute(\"lang\",\"en\"),i.className=\"lang-section lang-en\";const d=a.slice(s,l);if(d[0].before(i),d.forEach(e=>i.appendChild(e)),c!==-1){const e=document.createElement(\"section\");e.setAttribute(\"lang\",\"ko\"),e.className=\"lang-section lang-ko\";const t=Array.from(r.children),n=t.findIndex(o=>o.tagName===\"H2\"&&/^한국어$/i.test(o.textContent.trim()));if(n!==-1){const o=t.slice(n);o[0].before(e),o.forEach(m=>e.appendChild(m))}}});"],["C:/Users/user/Downloads/youtube-to-ebook/youtube-digest-archive/src/pages/issues/[...slug].astro?astro&type=script&index=3&lang.ts","document.addEventListener(\"DOMContentLoaded\",()=>{const e=\"yt-digest-read-issues\",t=window.location.pathname.replace(/^\\/issues\\//,\"\").replace(/\\/$/,\"\");if(t)try{const a=new Set(JSON.parse(localStorage.getItem(e)||\"[]\"));a.add(t),localStorage.setItem(e,JSON.stringify([...a]))}catch{}});"]],"assets":["/_astro/_slug_.B3GafXQf.css","/favicon.ico","/favicon.svg","/_astro/_...slug_.astro_astro_type_script_index_0_lang.CnK7EDOI.js","/_astro/_...slug_.astro_astro_type_script_index_1_lang.CJkItEj4.js","/index.html"],"buildFormat":"directory","checkOrigin":true,"allowedDomains":[],"actionBodySizeLimit":1048576,"serverIslandNameMap":[],"key":"hzNuB2jQcX5e3VkMkmjZbGJqpVKBAaE/TxSohyQGynI="});
if (manifest.sessionConfig) manifest.sessionConfig.driverModule = null;

export { manifest };

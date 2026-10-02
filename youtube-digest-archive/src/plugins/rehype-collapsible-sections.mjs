/**
 * Turn each article section into: heading (always visible)
 *   -> one-line summary (always visible)
 *   -> full text (collapsed behind a click)
 *
 * The issues are long — six episodes x two languages — so the default view is
 * a skim: every heading with a summary under it. Reading those summaries
 * top-to-bottom is meant to convey the whole issue; clicking one opens the
 * full section.
 *
 * The summary line comes from a `[[SUM]] ...` paragraph that the Python
 * pipeline injects right under each heading (see write_articles.
 * inject_section_summaries). When there is no marker — older issues that
 * predate the feature, plus the "Episode summary" block — the section's first
 * text paragraph is promoted to the summary line instead, so nothing is
 * duplicated and every section still collapses.
 *
 * Headings are deliberately left OUTSIDE the <details>: the page's TOC,
 * scroll-spy IntersectionObserver, and English/한국어 section wrapper all walk
 * the headings, and they must stay visible and stay direct children.
 */

const MARKER = '[[SUM]]';

// `[[AT:<video id>:<seconds>]]` — where this section's topic starts in the
// original video. Written by the pipeline on its own line after [[SUM]].
const CLIP_RE = /^\[\[AT:([\w-]{11}):(\d+)\]\]$/;

const isClipMarker = (node) => isElement(node, 'p') && CLIP_RE.test(textOf(node).trim());

function mmss(total) {
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	const pad = (n) => String(n).padStart(2, '0');
	return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/**
 * The "원본 영상 18:20" row. A plain link to YouTube at that second, so it
 * works without JavaScript; the issue page upgrades a click into an inline
 * player. No iframe is rendered up front — an issue has dozens of sections,
 * and dozens of embedded players would make the page crawl.
 */
function clipNode(videoId, seconds) {
	const t = mmss(seconds);
	return el('div', { className: ['sec-clip'] }, [
		el(
			'a',
			{
				className: ['clip-link'],
				href: `https://www.youtube.com/watch?v=${videoId}&t=${seconds}s`,
				target: '_blank',
				rel: 'noopener',
				dataVid: videoId,
				dataT: String(seconds),
			},
			[
				el('span', { className: ['clip-icon'], ariaHidden: 'true' }, [{ type: 'text', value: '▶' }]),
				{ type: 'text', value: '원본 영상 ' },
				el('span', { className: ['clip-time'] }, [{ type: 'text', value: t }]),
			]
		),
	]);
}

// Never collapsed: the language dividers separating English from 한국어.
const SKIP_HEADINGS = new Set(['english', '한국어']);

// Any heading closes the previous section; only these open a collapsible one
// (h1 is the article title — it holds no body of its own).
const ALL_HEADINGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']);
const COLLAPSIBLE_HEADINGS = new Set(['h2', 'h3', 'h4', 'h5', 'h6']);

/** Visible text of a hast node (image alt text doesn't count as text). */
function textOf(node) {
	if (!node) return '';
	if (node.type === 'text') return node.value || '';
	if (node.type === 'element' && node.tagName === 'img') return '';
	if (Array.isArray(node.children)) return node.children.map(textOf).join('');
	return '';
}

const norm = (s) => s.replace(/\s+/g, ' ').trim().toLowerCase();

const isWhitespace = (node) => node.type === 'text' && !node.value.trim();

const isElement = (node, tagName) =>
	node.type === 'element' && node.tagName === tagName;

/** A paragraph carrying real prose (not just a frame image). */
const isTextParagraph = (node) => isElement(node, 'p') && textOf(node).trim().length > 0;

/** Drop the leading `[[SUM]]` token from a paragraph's first text node. */
function stripMarker(paragraph) {
	const children = paragraph.children || [];
	for (const child of children) {
		if (child.type !== 'text') continue;
		if (!child.value.trim()) continue;
		child.value = child.value.replace(MARKER, '').replace(/^\s+/, '');
		break;
	}
	return paragraph;
}

const el = (tagName, properties, children) => ({
	type: 'element',
	tagName,
	properties,
	children,
});

export default function rehypeCollapsibleSections() {
	return (tree) => {
		const nodes = (tree.children || []).filter((n) => !isWhitespace(n));
		const out = [];
		let i = 0;

		while (i < nodes.length) {
			const node = nodes[i];
			const isHeading = node.type === 'element' && COLLAPSIBLE_HEADINGS.has(node.tagName);
			const isDivider = isHeading && SKIP_HEADINGS.has(norm(textOf(node)));

			// Tag the language dividers at build time so they're styled as
			// dividers on first paint, not after the client script runs.
			if (isDivider) {
				const cls = node.properties.className;
				node.properties.className = Array.isArray(cls)
					? [...cls, 'lang-divider']
					: ['lang-divider'];
			}

			if (!isHeading || isDivider) {
				out.push(node);
				i++;
				continue;
			}

			// Everything up to the next heading or article divider is this
			// section's body.
			let j = i + 1;
			const body = [];
			while (j < nodes.length) {
				const next = nodes[j];
				if (
					next.type === 'element' &&
					(ALL_HEADINGS.has(next.tagName) || next.tagName === 'hr')
				) {
					break;
				}
				body.push(next);
				j++;
			}

			// Pull the clip marker out first, so the no-[[SUM]] fallback below
			// can never promote it to the summary line.
			let clip = null;
			const clipIdx = body.findIndex(isClipMarker);
			if (clipIdx !== -1) {
				const [, vid, secs] = textOf(body.splice(clipIdx, 1)[0]).trim().match(CLIP_RE);
				clip = clipNode(vid, parseInt(secs, 10));
			}

			// Pull the summary line out of the body.
			let summaryChildren = null;
			if (body.length > 0 && isElement(body[0], 'p') && textOf(body[0]).trimStart().startsWith(MARKER)) {
				summaryChildren = stripMarker(body.shift()).children;
			} else {
				const idx = body.findIndex(isTextParagraph);
				if (idx !== -1) summaryChildren = body.splice(idx, 1)[0].children;
			}

			// No summary, or nothing left to hide — render the section as-is.
			if (!summaryChildren || body.length === 0) {
				out.push(node);
				if (summaryChildren) out.push(el('p', {}, summaryChildren));
				if (clip) out.push(clip);
				out.push(...body);
				i = j;
				continue;
			}

			out.push(node);
			out.push(
				el('details', { className: ['sec'] }, [
					el('summary', { className: ['sec-sum'] }, [
						el('span', { className: ['sec-sum-text'] }, summaryChildren),
						el('span', { className: ['sec-more'] }, []),
					]),
					el('div', { className: ['sec-body'] }, clip ? [clip, ...body] : body),
				])
			);
			i = j;
		}

		// Defense in depth: a marker under a heading that is never collapsed
		// (article title, language divider) would otherwise render literally.
		for (const node of out) {
			if (isElement(node, 'p') && textOf(node).trimStart().startsWith(MARKER)) {
				stripMarker(node);
			}
		}

		tree.children = out.filter((node) => !isClipMarker(node));
	};
}

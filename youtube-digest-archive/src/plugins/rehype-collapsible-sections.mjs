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
			const isCollapsible =
				node.type === 'element' &&
				COLLAPSIBLE_HEADINGS.has(node.tagName) &&
				!SKIP_HEADINGS.has(norm(textOf(node)));

			if (!isCollapsible) {
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
					el('div', { className: ['sec-body'] }, body),
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

		tree.children = out;
	};
}

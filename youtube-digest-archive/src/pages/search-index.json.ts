import type { APIRoute } from 'astro';
import { getCollection, render } from 'astro:content';

/**
 * Build-time search index: every heading in every issue, paired with the
 * one-line summary that sits under it, in both English and Korean.
 *
 * Two reasons this is a separate file rather than data on the index page:
 * the archive is ~4,000 headings, which is far too much to inline into the
 * page everyone loads, and it's only needed once someone actually types.
 * The index page fetches it on the first keystroke.
 *
 * Slugs come from Astro's own `render()`, not a re-implementation of its
 * slugger, so the anchors are guaranteed to match the rendered headings.
 */

const SUM = '[[SUM]]';

// Summaries average ~157 characters, and 4,700 of them at full length make a
// 519 KB (gzipped) download. The opening clause carries the distinctive words
// that searches actually hit, so it's cut to the first sentence or 100
// characters — whichever comes first.
const SNIPPET = 100;

function snippet(text: string): string {
	if (text.length <= SNIPPET) return text;
	const cut = text.slice(0, SNIPPET);
	const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('다. '));
	return (stop > SNIPPET * 0.5 ? cut.slice(0, stop + 1) : cut.trimEnd() + '…');
}

// Never worth a search hit: the language dividers and the summary label.
const SKIP = new Set(['english', '한국어', 'episode summary', '에피소드 요약']);

const norm = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase();

/** Map heading text -> the `[[SUM]]` line written under it. */
function summariesByHeading(body: string): Map<string, string> {
	const out = new Map<string, string>();
	let current = '';
	let inFence = false;

	for (const line of body.split('\n')) {
		if (line.startsWith('```')) {
			inFence = !inFence;
			continue;
		}
		if (inFence) continue;

		const heading = line.match(/^#{1,6}\s+(.+?)\s*$/);
		if (heading) {
			current = norm(heading[1]);
			continue;
		}
		if (current && line.startsWith(SUM)) {
			out.set(current, line.slice(SUM.length).trim());
			current = '';
		}
	}
	return out;
}

export const GET: APIRoute = async () => {
	const issues = await getCollection('issues');
	issues.sort((a, b) => new Date(b.data.date).valueOf() - new Date(a.data.date).valueOf());

	const entries = [];
	for (const issue of issues) {
		const { headings } = await render(issue);
		const summaries = summariesByHeading(issue.body ?? '');

		// Short keys — this file is shipped to the browser.
		//   s: anchor slug, t: heading text, d: its summary, l: heading depth
		const items = headings
			.filter((h) => !SKIP.has(norm(h.text)))
			.map((h) => ({
				s: h.slug,
				t: h.text,
				d: snippet(summaries.get(norm(h.text)) ?? ''),
				l: h.depth,
			}))
			.filter((i) => i.t);

		entries.push({
			id: issue.id,
			subject: issue.data.subject,
			items,
		});
	}

	return new Response(JSON.stringify(entries), {
		headers: { 'Content-Type': 'application/json; charset=utf-8' },
	});
};

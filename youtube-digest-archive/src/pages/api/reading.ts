export const prerender = false;

import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';

/**
 * Read-aloud feed for Velora's 낭독 screen.
 *
 * Serves the newest issue's episodes as ~2-minute English passages (the
 * per-episode summary, not the full article — a 3,000-word article is a
 * 25-minute read-aloud, which nobody sustains daily).
 *
 * Runtime route rather than a prerendered .json file on purpose: Velora runs
 * on a different origin, and a static file can't carry the CORS header the
 * browser needs (the Vercel adapter's Build Output config ignores vercel.json
 * headers).
 */

const CORS = {
	'Content-Type': 'application/json; charset=utf-8',
	'Access-Control-Allow-Origin': '*',
	// One issue a day — a few minutes of caching is plenty and keeps a
	// re-opened app from re-invoking the function.
	'Cache-Control': 'public, max-age=300, s-maxage=300',
};

const issueDay = (date: string | Date): string =>
	date instanceof Date ? date.toISOString().slice(0, 10) : String(date).slice(0, 10);

export const GET: APIRoute = async ({ url }) => {
	const issues = await getCollection('issues');
	if (issues.length === 0) {
		return new Response(JSON.stringify({ error: 'no issues' }), { status: 404, headers: CORS });
	}

	const newest = issues.sort(
		(a, b) => new Date(b.data.date).valueOf() - new Date(a.data.date).valueOf()
	)[0];

	const articles = (newest.data.articles ?? [])
		.filter((a) => a.summary && a.summary.trim())
		.map((a) => ({
			title: a.title,
			channel: a.channel,
			videoUrl: a.url,
			text: a.summary.trim(),
		}));

	return new Response(
		JSON.stringify({
			date: issueDay(newest.data.date),
			issue: newest.id,
			issueUrl: new URL(`/issues/${newest.id}`, url.origin).href,
			articles,
		}),
		{ headers: CORS }
	);
};

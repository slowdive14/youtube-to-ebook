export const prerender = false;

import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';

/**
 * Listening feed for Velora's podcast player.
 *
 *   GET /api/listening          → the recent episodes, without transcripts
 *   GET /api/listening?id=<id>  → one episode with its full transcript
 *
 * The list stays small (a transcript is ~50-90KB); Velora fetches a
 * transcript only for the episode actually being played.
 *
 * Runtime route for the same reason as /api/reading: Velora is another
 * origin and needs the CORS header, which a static file can't carry here.
 */

const HEADERS = {
	'Content-Type': 'application/json; charset=utf-8',
	'Access-Control-Allow-Origin': '*',
	'Cache-Control': 'public, max-age=300, s-maxage=300',
};

const LIST_LIMIT = 20;

export const GET: APIRoute = async ({ url }) => {
	const all = await getCollection('listening');
	const id = url.searchParams.get('id');

	if (id) {
		const entry = all.find((e) => e.data.id === id);
		if (!entry) {
			return new Response(JSON.stringify({ error: 'not found' }), { status: 404, headers: HEADERS });
		}
		return new Response(JSON.stringify(entry.data), { headers: HEADERS });
	}

	const episodes = all
		.map((e) => e.data)
		.sort(
			(a, b) =>
				b.addedAt.localeCompare(a.addedAt) || b.releaseDate.localeCompare(a.releaseDate)
		)
		.slice(0, LIST_LIMIT)
		.map(({ segments, ...meta }) => ({
			...meta,
			segmentCount: segments.length,
			// One line of what the episode is about, for the list.
			preview: segments.find((s) => !s.ad)?.ko ?? '',
		}));

	return new Response(JSON.stringify({ episodes }), { headers: HEADERS });
};

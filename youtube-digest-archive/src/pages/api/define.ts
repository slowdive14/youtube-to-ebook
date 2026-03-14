export const prerender = false;

import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  const apiKey = import.meta.env.GEMINI_API_KEY;
  if (!apiKey) {
    return new Response(JSON.stringify({ error: 'API key not configured' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  let body: { text: string; context?: string };
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const { text, context } = body;
  if (!text || text.length > 500) {
    return new Response(JSON.stringify({ error: 'Text required (max 500 chars)' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const isWord = text.trim().split(/\s+/).length <= 3;

  const prompt = isWord
    ? `You are an English-Korean dictionary assistant for Korean learners.

The user selected the word/phrase: "${text}"
${context ? `Context sentence: "${context}"` : ''}

Respond in this exact format (no markdown, plain text):
[발음] (phonetic pronunciation in Korean, e.g. 컨프런트)
[뜻] (Korean meaning, concise, 1-2 meanings max)
[문맥] (1 sentence in Korean explaining what it means in this specific context)

Keep it very concise. No English explanations.`
    : `You are an English-Korean translation assistant for Korean learners.

The user selected this passage: "${text}"
${context ? `Surrounding context: "${context}"` : ''}

Respond in this exact format (no markdown, plain text):
[해석] (Natural Korean translation of the selected text)
[핵심] (1 sentence explaining the key point or nuance in Korean)

Keep it concise. No English explanations.`;

  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: 0.3,
            maxOutputTokens: 256,
          },
        }),
      }
    );

    if (!res.ok) {
      const errText = await res.text();
      console.error('Gemini API error:', errText);
      return new Response(JSON.stringify({ error: 'AI service error' }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const data = await res.json();
    const result = data?.candidates?.[0]?.content?.parts?.[0]?.text || '';

    return new Response(JSON.stringify({ result }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error('Gemini fetch error:', err);
    return new Response(JSON.stringify({ error: 'Failed to reach AI service' }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

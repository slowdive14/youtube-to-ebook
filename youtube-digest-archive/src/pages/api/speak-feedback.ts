export const prerender = false;

import type { APIRoute } from 'astro';

// Audio container types Gemini accepts (codecs param is stripped before check)
const ALLOWED_MIME = new Set([
  'audio/webm',
  'audio/ogg',
  'audio/mp4',
  'audio/mpeg',
  'audio/wav',
  'audio/x-wav',
  'audio/aac',
  'audio/x-m4a',
]);

// ~3MB of base64 ≈ ~2.2MB audio — plenty for a one-sentence clip
const MAX_AUDIO_BASE64 = 3_000_000;

const COACH_PROMPT = `You are a warm, encouraging English speaking coach for a Korean B1 learner.
The learner was given this task (Korean): "{{QUESTION}}"
A natural model answer is: "{{MODEL}}"
The attached audio is the learner SPEAKING their own one-sentence answer.

First TRANSCRIBE exactly what they said (do your best with the accent; never
penalize accent). Then coach gently — NEVER say "wrong". Build confidence.

Respond with ONLY a JSON object (no markdown) with these keys:
{
  "transcript": "what the learner actually said, verbatim",
  "good": "one specific thing they did well, in Korean",
  "corrected": "their sentence rewritten to sound natural, in English",
  "upgrade": "one better word/expression to learn, in English, with a short Korean gloss in parentheses",
  "model_answer": "a natural model answer they can shadow, in English, <= 20 words"
}
If the audio is empty or unintelligible, set transcript to "" and still return
encouraging guidance using the model answer.`;

export const POST: APIRoute = async ({ request }) => {
  const apiKey = process.env.GEMINI_API_KEY || import.meta.env.GEMINI_API_KEY;
  if (!apiKey) {
    return json({ error: 'API key not configured' }, 500);
  }

  let body: { audioBase64?: string; mimeType?: string; question?: string; model?: string };
  try {
    body = await request.json();
  } catch {
    return json({ error: 'Invalid request' }, 400);
  }

  const { audioBase64, mimeType, question = '', model = '' } = body;
  if (!audioBase64 || typeof audioBase64 !== 'string') {
    return json({ error: 'audioBase64 required' }, 400);
  }
  if (audioBase64.length > MAX_AUDIO_BASE64) {
    return json({ error: 'Audio too large' }, 413);
  }
  const baseMime = (mimeType || '').split(';')[0].trim().toLowerCase();
  if (!ALLOWED_MIME.has(baseMime)) {
    return json({ error: `Unsupported audio type: ${baseMime || 'none'}` }, 415);
  }

  const prompt = COACH_PROMPT
    .replace('{{QUESTION}}', question.slice(0, 500))
    .replace('{{MODEL}}', model.slice(0, 300));

  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [
            {
              parts: [
                { text: prompt },
                { inlineData: { mimeType: baseMime, data: audioBase64 } },
              ],
            },
          ],
          generationConfig: {
            temperature: 0.3,
            maxOutputTokens: 800,
            responseMimeType: 'application/json',
            thinkingConfig: { thinkingBudget: 0 },
          },
        }),
      }
    );

    if (!res.ok) {
      const errText = await res.text();
      console.error('Gemini API error:', errText.slice(0, 300));
      return json({ error: 'AI service error' }, 502);
    }

    const data = await res.json();
    const parts = data?.candidates?.[0]?.content?.parts || [];
    const answerPart = parts.filter((p: any) => !p.thought).pop();
    const raw = answerPart?.text || parts[parts.length - 1]?.text || '';

    let feedback: any;
    try {
      feedback = JSON.parse(stripFence(raw));
    } catch {
      return json({ error: 'Could not parse feedback', raw: raw.slice(0, 200) }, 502);
    }

    return json({
      transcript: feedback.transcript ?? '',
      good: feedback.good ?? '',
      corrected: feedback.corrected ?? '',
      upgrade: feedback.upgrade ?? '',
      model_answer: feedback.model_answer ?? model,
    }, 200);
  } catch (err) {
    console.error('Gemini fetch error:', err);
    return json({ error: 'Failed to reach AI service' }, 502);
  }
};

function stripFence(s: string): string {
  const t = s.trim();
  if (t.startsWith('```')) {
    return t.replace(/^```[a-z]*\n?/i, '').replace(/```$/, '').trim();
  }
  return t;
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

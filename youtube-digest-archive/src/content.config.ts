import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const issues = defineCollection({
    loader: glob({ pattern: "**/*.md", base: "./src/content/issues" }),
    schema: z.object({
        title: z.string(),
        date: z.string().or(z.date()),
        subject: z.string(),
        audioUrls: z.array(z.string()).optional(),
        articles: z.array(
            z.object({
                title: z.string(),
                channel: z.string(),
                url: z.string(),
            })
        ).optional(),
        drillSentences: z.array(
            z.object({
                sentence: z.string(),
                korean: z.string(),
                blank: z.string(),
                blank_answer: z.string(),
                pattern: z.string(),
                variation_hint: z.string(),
            })
        ).optional(),
    }),
});

export const collections = { issues };

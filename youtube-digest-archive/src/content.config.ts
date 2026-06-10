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
                swap_word: z.string(),
            })
        ).optional(),
        speakingPrompt: z.object({
            topic: z.string().optional().default(''),
            question_ko: z.string(),
            frame: z.string(),
            model: z.string(),
            expressions: z.array(
                z.object({
                    en: z.string(),
                    ko: z.string().optional().default(''),
                })
            ).optional().default([]),
            shadow: z.array(
                z.object({
                    en: z.string(),
                    ko: z.string().optional().default(''),
                })
            ).optional().default([]),
            patterns: z.array(
                z.object({
                    pattern: z.string(),
                    pattern_ko: z.string().optional().default(''),
                    s1_en: z.string(),
                    s1_ko: z.string().optional().default(''),
                    s2_en: z.string(),
                    s2_ko: z.string().optional().default(''),
                    s2_answer: z.string().optional().default(''),
                })
            ).optional().default([]),
        }).optional(),
    }),
});

export const collections = { issues };

// Site-level feature switches.
// Flip a flag back to `true` to restore the feature — no code was removed.
export const FEATURES = {
	// 오디오(팟캐스트) 플레이어. 생성 자체는 파이썬 쪽 ENABLE_PODCAST 로 꺼져 있음.
	audio: false,
	// 리더 모드(/issues/<id>/read) 링크. 페이지 자체는 그대로 남아 있음.
	readerMode: false,
};

// Article categories = the subject areas the pipeline sorts videos into
// (select_videos.DOMAINS), in the order the archive's filter shows them.
// The ids are what frontmatter `articles[].category` holds.
export const CATEGORIES = [
	{ id: 'technology', label: 'AI·기술' },
	{ id: 'politics', label: '정치·국제' },
	{ id: 'business', label: '경제·비즈니스' },
	{ id: 'culture', label: '문화·사회' },
	{ id: 'health', label: '심리·건강' },
	{ id: 'science', label: '과학' },
	{ id: 'other', label: '기타' },
] as const;

export const categoryLabel = (id: string): string =>
	CATEGORIES.find((c) => c.id === id)?.label ?? '';

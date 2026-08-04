// Site-level feature switches.
// Flip a flag back to `true` to restore the feature — no code was removed.
export const FEATURES = {
	// 오디오(팟캐스트) 플레이어. 생성 자체는 파이썬 쪽 ENABLE_PODCAST 로 꺼져 있음.
	audio: false,
	// 리더 모드(/issues/<id>/read) 링크. 페이지 자체는 그대로 남아 있음.
	readerMode: false,
};

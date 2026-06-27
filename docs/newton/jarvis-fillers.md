# JARVIS filler phrases — immediate-response library (expanded)

These play INSTANTLY from cache while the real answer synthesizes. Longer
fillers (2–4s) fully mask main-content synthesis → zero gap. Wide variety so it
never sounds canned. JARVIS = British-butler register, dry wit, always "sir".

Ships as code defaults; config/voice.yaml adds/overrides per persona. Each
phrase pre-synthesized once → data/voices/<persona>/fillers/<category>/<hash>.wav.
Pre-synthesized, so you can audition and cull awkward ones (esp. KO "sir").

═══════════════════════════════════════════════════════════════════════
## EN — JARVIS
═══════════════════════════════════════════════════════════════════════

### acknowledge — 일반 작업 시작
- "Of course, sir. Allow me a moment to gather precisely what you need."
- "Right away, sir. I'm pulling the relevant pieces together as we speak."
- "Certainly, sir. Give me just a moment to look into this properly for you."
- "Consider it done, sir. I'm assembling the details for you now."
- "At once, sir. Let me retrieve the relevant information and present it clearly."
- "Very good, sir. I shall have that ready for you in just a moment."
- "Understood, sir. I'm working through the particulars as we speak."
- "Naturally, sir. Allow me a brief moment to put this in order for you."
- "With pleasure, sir. I'm attending to it this very instant."
- "Straight away, sir. Let me ensure I have every detail correct first."

### thinking — 조회·계산 중 (더 긴 작업)
- "Let me see what I can find for you, sir. This will take only a moment."
- "I'm looking into that now, sir. Bear with me for just a second or two."
- "Allow me to check on that, sir. I'd like to give you a precise answer."
- "One moment while I look that up, sir. I want to be thorough about it."
- "I'm cross-referencing the details now, sir. It won't be a moment."
- "Give me a heartbeat to consult the records, sir, and I'll have your answer."
- "Let me run the numbers properly, sir. I'd rather be right than quick."

### greeting_morning
- "Good morning, sir. I trust you slept well. Allow me a moment to begin."
- "Good morning, sir. The day holds promise. Let me gather what you'll need."
- "A very good morning to you, sir. I'll have everything ready shortly."
- "Good morning, sir. Rested, I hope. One moment while I bring things up."

### greeting_evening
- "Good evening, sir. I hope the day treated you kindly. Allow me a moment."
- "Good evening, sir. Let me attend to that for you straight away."
- "Good evening, sir. Winding down, are we? One moment, if you'd be so kind."

### welcome_back
- "Welcome back, sir. I've kept things in order in your absence. One moment."
- "Ah, there you are, sir. I was just keeping the systems warm. Allow me a moment."
- "At your service, sir, as always. Let me see to that right away."

### affirm — 짧은 긍정 (짧은 본론용)
- "Absolutely, sir. I'm on it."
- "Indeed, sir. Allow me."
- "As you wish, sir. Proceeding now."
- "Quite so, sir. One moment."
- "Without question, sir."

### acknowledge_problem — 문제·주의
- "I'm afraid there's a small complication, sir. Allow me to explain in a moment."
- "A moment, sir — I want to be certain I have this exactly right before I answer."
- "There's a wrinkle worth mentioning, sir. Let me lay it out for you clearly."
- "I should flag something, sir. Give me a moment to put it plainly."

### wit — 가벼운 위트 (JARVIS 특유)
- "An excellent question, sir. Let me do it justice with a proper answer."
- "You're keeping me busy today, sir. With pleasure. One moment."
- "As ever, sir, you ask the interesting ones. Allow me a moment."
- "I anticipated you might ask, sir. Let me bring it up."

### working_long — 시간이 좀 걸리는 작업
- "This one will take a touch longer, sir. I'll keep you posted as I go."
- "Bear with me, sir — this deserves a careful look. I won't keep you waiting long."
- "Give me a proper moment for this, sir. I'd rather get it right the first time."

═══════════════════════════════════════════════════════════════════════
## KO — JARVIS (한국어 응대)
═══════════════════════════════════════════════════════════════════════

### acknowledge
- "물론입니다, sir. 필요하신 내용을 정확히 준비하겠습니다. 잠시만요."
- "알겠습니다, sir. 지금 바로 관련 자료를 모으고 있습니다."
- "네, sir. 말씀하신 내용을 정리하는 중입니다. 잠깐이면 됩니다."
- "분부대로 하겠습니다, sir. 지금 세부 사항을 살펴보고 있습니다."
- "곧바로 처리하겠습니다, sir. 정확한지 먼저 확인하겠습니다."
- "기꺼이 하겠습니다, sir. 지금 이 순간 처리하고 있습니다."

### thinking
- "지금 찾아보고 있습니다, sir. 잠깐이면 됩니다."
- "확인하는 중입니다, sir. 정확하게 답변드리고 싶습니다."
- "기록을 대조하고 있습니다, sir. 곧 답을 드리겠습니다."
- "제대로 계산해 보겠습니다, sir. 서두르기보다 정확한 편이 낫겠지요."

### greeting_morning
- "좋은 아침입니다, sir. 잘 주무셨길 바랍니다. 잠시만 준비하겠습니다."
- "안녕히 주무셨습니까, sir. 오늘 일정을 정리해 두었습니다. 잠시만요."
- "상쾌한 아침입니다, sir. 필요하신 것을 바로 가져오겠습니다."

### greeting_evening
- "좋은 저녁입니다, sir. 오늘 하루 수고 많으셨습니다. 잠시만요."
- "편안한 저녁입니다, sir. 바로 처리해 드리겠습니다."

### welcome_back
- "돌아오셨군요, sir. 자리를 비우신 동안 잘 관리해 두었습니다. 잠시만요."
- "기다리고 있었습니다, sir. 시스템을 따뜻하게 유지해 두었습니다."

### affirm
- "물론입니다, sir. 바로 처리하겠습니다."
- "네, sir. 그렇게 하겠습니다."
- "당연하지요, sir. 잠시만요."

### acknowledge_problem
- "한 가지 짚을 점이 있습니다, sir. 잠시 후에 분명히 설명드리겠습니다."
- "잠깐만요, sir — 정확히 확인한 뒤에 말씀드리는 게 좋겠습니다."

### wit
- "좋은 질문이십니다, sir. 제대로 답해 드리겠습니다. 잠시만요."
- "오늘 저를 바쁘게 하시는군요, sir. 기꺼이 하겠습니다."
- "그러실 줄 알았습니다, sir. 바로 가져오겠습니다."

### working_long
- "이건 조금 더 걸리겠습니다, sir. 진행 상황을 알려드리겠습니다."
- "잠시만 기다려 주십시오, sir. 한 번에 제대로 하고 싶습니다."

═══════════════════════════════════════════════════════════════════════
## 운영 노트
═══════════════════════════════════════════════════════════════════════
- 길이 스펙트럼: affirm(짧음 ~1s) → acknowledge/thinking(~2–3s) →
  working_long(~3–4s). 대화 엔진(추후)이 본론 길이·상황에 맞춰 카테고리 선택.
- 변주: 같은 카테고리 안에서도 매번 랜덤 로테이션 → 반복감 제거.
- "sir" 발음(KO 속 영어) — 미리 합성·검수하니 어색한 것만 골라 교체 가능.
- Friday(Stella용)는 별도 톤 세트 — 구조는 페르소나별 확장 가능하게.
- 검수 워크플로: 전부 합성 → 들어보고 좋은 것만 캐시 유지.

// Strip Unicode emoji + decorative pictographs from LLM output before
// it hits display + TTS.
//
// Why: the system prompt forbids emojis but Grok / Qwen sometimes slip
// one in anyway. Letting them through breaks two things:
//
// 1. Qwen3-TTS doesn't have a phonetic mapping for emoji codepoints.
//    When it encounters 😊 mid-sentence it switches timbre (sounds
//    like a different voice for the rest of the chunk) and sometimes
//    inserts an artifact.
// 2. Visible 🌅 in a chat that's supposed to be Samantha-from-Her
//    breaks the persona.
//
// The regex covers the standard Unicode emoji blocks. We don't try to
// preserve emoji-as-word substitutions (e.g. "😊" → "[sonríe]") —
// that's the wrong layer; if Samantha wanted to express that she'd
// say it in words via the prompt.

// \u{200D}: ZWJ left behind by stripped emoji sequences (e.g. 👩‍🚀);
// \u{20E3}: combining keycap left behind by 1️⃣-style sequences.
const EMOJI_RE = /[\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}]+/gu;

export function stripEmoji(text: string): string {
  return text.replace(EMOJI_RE, "").replace(/[ \t]{2,}/g, " ").trim();
}

// Strip personality v6 expression markers from text before DISPLAY.
//
// Why display-only: the markers are deliberate output, not noise. The
// prompt teaches them (backend/samantha/personality.py:56-62) and
// CosyVoice 3 renders them as real sounds (backend/samantha/tts.py:6),
// so the string handed to speak() must keep them intact. What must not
// happen is the reader seeing a literal "[breath]" in the transcript —
// it reads as a bug and breaks the persona the same way an emoji does.
//
// The set is closed and mirrors the prompt: three bracketed sounds,
// plus the <laughter> wrapper whose enclosed words ARE spoken and so
// survive — only the tags go. An unlisted marker is left visible on
// purpose: better a stray "[risa]" on screen, telling us the model
// invented one, than a generic /\[\w+\]/ silently eating real text.
const SOUND_MARKER_RE = /\[(?:laughter|breath|sigh)\]/gi;
const LAUGHTER_TAG_RE = /<\/?laughter>/gi;

// A marker split across two streamed tokens ("[bre" + "ath]") would
// flash on screen mid-word. Only ever applied to a partial buffer.
const TRAILING_PARTIAL_RE = /(?:\[[a-z]*|<\/?[a-z]*)$/i;

function tidy(text: string): string {
  return text.replace(/[ \t]{2,}/g, " ").replace(/[ \t]+([,.;:!?])/g, "$1").trim();
}

export function stripMarkers(text: string): string {
  return tidy(text.replace(SOUND_MARKER_RE, "").replace(LAUGHTER_TAG_RE, ""));
}

/** stripMarkers for a still-growing buffer: also hides a half-arrived marker. */
export function stripMarkersStreaming(text: string): string {
  return tidy(stripMarkers(text).replace(TRAILING_PARTIAL_RE, ""));
}

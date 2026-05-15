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

const EMOJI_RE = /[\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{FE00}-\u{FE0F}]+/gu;

export function stripEmoji(text: string): string {
  return text.replace(EMOJI_RE, "").replace(/[ \t]{2,}/g, " ").trim();
}

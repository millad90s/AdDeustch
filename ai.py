"""Pluggable AI provider layer for generating career-specific example sentences.

The provider is chosen via the AI_PROVIDER env var (default: "claude"). Add more
providers by implementing AIProvider and registering them in PROVIDERS — e.g. to
pick a cheaper platform for some deployments.

Claude (Anthropic) is the reference implementation. It needs ANTHROPIC_API_KEY;
without it, generation is simply unavailable and the app falls back to whatever
sentences already exist in the database.
"""
import json
import os
import re


def _setting(db_key, env_key, default=None):
    """Resolve a config value: dashboard-managed DB setting first, then env var,
    then default. Lets admins manage provider/keys/models from the UI."""
    try:
        import db
        v = db.get_setting(db_key)
        if v:
            return v
    except Exception:
        pass
    return os.getenv(env_key) or default


class AIProvider:
    name = "base"

    def available(self) -> bool:
        return False

    def generate_sentences(self, word, career, level, n=3):
        """Return a list of (sentence_de, sentence_en) tuples, or [] on failure."""
        raise NotImplementedError


# Guidance per CEFR level so generated sentences stay at the learner's level and
# don't introduce advanced/rare vocabulary above what they selected.
_LEVEL_GUIDE = {
    "A1": "absolute beginner. Use only the most common everyday words, present "
          "tense, very short main clauses (no subordinate clauses).",
    "A2": "elementary. Use common everyday words, mostly present/perfect tense, "
          "simple sentences; avoid rare or technical vocabulary.",
    "B1": "intermediate. Use common vocabulary and straightforward grammar; you may "
          "use simple subordinate clauses but avoid rare, academic or flowery words.",
    "B2": "upper-intermediate. Natural everyday and professional vocabulary is fine, "
          "but still avoid rare, literary or needlessly complex words.",
    "C1": "advanced. Richer vocabulary and complex sentences are acceptable.",
    "C2": "proficient. Sophisticated, idiomatic German is acceptable.",
}


def _build_prompt(word, career, level, n):
    guide = _LEVEL_GUIDE.get((level or "").upper().strip(),
                             "an intermediate (B1) learner; keep vocabulary common "
                             "and avoid rare or advanced words.")
    return (
        f"Create {n} example sentences in German that naturally use the word "
        f"\"{word}\".\n"
        f"- The learner works as: {career}.\n"
        f"- The learner's CEFR level is {level}: write for {guide}\n"
        "- Stay AT or BELOW this level. Apart from the target word itself, use only "
        "vocabulary a learner at this level would know — no advanced, rare, literary "
        "or unnecessarily technical words. If a simpler word works, use it.\n"
        "Make the sentences realistic and relevant to that job, professional in "
        "tone, and clearly using the target word. Keep each sentence concise "
        "(about 6–14 words). Give an accurate English translation for each.\n\n"
        "Respond with ONLY a JSON object of this exact shape, no prose, no code "
        "fences:\n"
        '{"sentences": [{"de": "<German sentence>", "en": "<English translation>"}]}'
    )


def _parse_sentences(text):
    """Extract (de, en) pairs from the model's JSON reply, tolerating stray text."""
    if not text:
        return []
    # strip code fences if present, then grab the first {...} block
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for item in (data.get("sentences") or []):
        de = (item.get("de") or "").strip()
        en = (item.get("en") or "").strip()
        if de and en:
            out.append((de, en))
    return out


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self):
        self.api_key = _setting("anthropic_api_key", "ANTHROPIC_API_KEY", "")
        self.model = _setting("anthropic_model", "ANTHROPIC_MODEL", "claude-opus-4-8")
        self._client = None

    def available(self):
        return bool(self.api_key)

    def _client_or_none(self):
        if self._client is None:
            import anthropic  # imported lazily so the app runs without the package
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def generate_sentences(self, word, career, level, n=3):
        if not self.available():
            return []
        try:
            client = self._client_or_none()
            resp = client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=(
                    "You are a German language teacher writing example sentences "
                    "for a professional learning German for their career."
                ),
                messages=[{"role": "user", "content": _build_prompt(word, career, level, n)}],
            )
            text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
            return _parse_sentences(text)[:n]
        except Exception:
            return []


class GeminiProvider(AIProvider):
    """Google Gemini 2.5 Flash / Flash-Lite — a cheaper, fast alternative.

    Needs GEMINI_API_KEY (or GOOGLE_API_KEY). Model via GEMINI_MODEL, default
    "gemini-2.5-flash" (use "gemini-2.5-flash-lite" for the cheapest option).
    Uses the unified `google-genai` SDK.
    """
    name = "gemini"
    _SYSTEM = ("You are a German language teacher writing example sentences "
               "for a professional learning German for their career.")

    def __init__(self):
        self.api_key = _setting("gemini_api_key", "GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self.model = _setting("gemini_model", "GEMINI_MODEL", "gemini-2.5-flash")
        self._client = None

    def available(self):
        return bool(self.api_key)

    def _client_or_none(self):
        if self._client is None:
            from google import genai  # imported lazily so the app runs without the package
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # A strict JSON schema makes the model return well-formed output every time,
    # which removes most parse failures.
    _SCHEMA = {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"de": {"type": "string"}, "en": {"type": "string"}},
                    "required": ["de", "en"],
                },
            }
        },
        "required": ["sentences"],
    }

    def generate_sentences(self, word, career, level, n=3):
        if not self.available():
            return []
        try:
            from google.genai import types
            client = self._client_or_none()
            resp = client.models.generate_content(
                model=self.model,
                contents=_build_prompt(word, career, level, n),
                config=types.GenerateContentConfig(
                    system_instruction=self._SYSTEM,
                    response_mime_type="application/json",
                    response_schema=self._SCHEMA,   # guarantees valid JSON shape
                    temperature=0.7,
                    max_output_tokens=4096,         # headroom so output isn't truncated
                    # Disable "thinking": simple task, faster/cheaper, and avoids
                    # thinking tokens eating the output budget (a cause of empties).
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            return _parse_sentences(self._text(resp))[:n]
        except Exception:
            return []

    @staticmethod
    def _text(resp):
        """Robustly pull text out of a response (resp.text raises when blocked)."""
        try:
            t = resp.text
            if t:
                return t
        except Exception:
            pass
        try:
            return "".join(
                p.text or "" for c in (resp.candidates or [])
                for p in (c.content.parts or []) if getattr(p, "text", None)
            )
        except Exception:
            return ""


# Register additional providers here (e.g. an OpenAI-backed one) to switch by price.
PROVIDERS = {"claude": ClaudeProvider, "gemini": GeminiProvider}


def get_provider():
    name = _setting("ai_provider", "AI_PROVIDER", "claude").lower()
    cls = PROVIDERS.get(name, ClaudeProvider)
    return cls()

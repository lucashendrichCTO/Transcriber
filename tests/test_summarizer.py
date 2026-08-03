"""
Unit tests for summarizer.summarize_transcript().

The real GGUF model is never loaded here — _complete (the only function that
talks to the model) is monkeypatched, so these tests run fast with no download.
A real-model integration test is gated behind the `summarization` marker and an
opt-in env var, since it downloads a multi-GB model on first run.
"""
import os

import pytest

import summarizer


def test_empty_text_returns_empty_string():
    assert summarizer.summarize_transcript("") == ""


def test_whitespace_only_text_returns_empty_string():
    assert summarizer.summarize_transcript("   \n\t  ") == ""


def test_short_transcript_is_a_single_chunk(monkeypatch):
    calls = []

    def fake_complete(prompt, max_tokens=700):
        calls.append(prompt)
        return "a short summary"

    monkeypatch.setattr(summarizer, "_complete", fake_complete)
    result = summarizer.summarize_transcript("Alice: let's ship the feature. Bob: agreed.")

    assert result == "a short summary"
    assert len(calls) == 1  # one chunk — no reduce step needed


def test_long_transcript_uses_map_reduce(monkeypatch):
    monkeypatch.setattr(summarizer, "_CHUNK_CHARS", 100)
    text = "sentence about the meeting. " * 20  # well over 100 chars

    calls = []

    def fake_complete(prompt, max_tokens=700):
        calls.append(prompt)
        if "consecutive parts" in prompt:
            return "combined summary"
        return f"chunk summary {len(calls)}"

    monkeypatch.setattr(summarizer, "_complete", fake_complete)
    result = summarizer.summarize_transcript(text)

    assert result == "combined summary"
    assert len(calls) > 2  # multiple chunk calls + one reduce call
    assert "consecutive parts" in calls[-1]  # reduce step ran last


def test_map_reduce_reduce_prompt_includes_chunk_summaries(monkeypatch):
    monkeypatch.setattr(summarizer, "_CHUNK_CHARS", 50)
    text = "word " * 40

    reduce_prompts = []

    def fake_complete(prompt, max_tokens=700):
        if "consecutive parts" in prompt:
            reduce_prompts.append(prompt)
            return "final summary"
        return "CHUNK-MARKER"

    monkeypatch.setattr(summarizer, "_complete", fake_complete)
    result = summarizer.summarize_transcript(text)

    assert result == "final summary"
    assert len(reduce_prompts) == 1
    assert "CHUNK-MARKER" in reduce_prompts[0]


def test_return_type_is_always_str(monkeypatch):
    monkeypatch.setattr(summarizer, "_complete", lambda prompt, max_tokens=700: "x")
    for text in ["", "   ", "short transcript", "word " * 5000]:
        assert isinstance(summarizer.summarize_transcript(text), str)


# ---------------------------------------------------------------------------
# Real-model integration test — opt-in only, downloads the GGUF model
# ---------------------------------------------------------------------------

requires_real_model = pytest.mark.skipif(
    os.environ.get("TRANSCRIBER_RUN_SUMMARIZATION_TESTS") != "1",
    reason="set TRANSCRIBER_RUN_SUMMARIZATION_TESTS=1 to run (downloads a multi-GB model)",
)


@pytest.mark.summarization
@requires_real_model
def test_real_model_summarizes_short_transcript():
    text = (
        "Alice: Let's finalize the Q3 roadmap. Bob: I think we should prioritize "
        "the mobile redesign. Alice: Agreed, let's assign that to the mobile team "
        "by Friday. Bob: I'll send the ticket."
    )
    result = summarizer.summarize_transcript(text)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.summarization
@requires_real_model
def test_real_model_does_not_hallucinate_on_sparse_transcript():
    """Regression test for a reported bug: a trivial, content-free transcript
    caused the model to fabricate an entire fictional meeting (product launch,
    marketing budget, new hires, etc.) instead of reporting that there was
    nothing to summarize. Uses the exact transcript from the bug report."""
    text = "This is a test of the current scriber meeting summary."
    result = summarizer.summarize_transcript(text)

    assert isinstance(result, str)
    fabricated_terms = [
        "product launch", "marketing", "budget", "social media",
        "new team member", "reconvene",
    ]
    lowered = result.lower()
    for term in fabricated_terms:
        assert term not in lowered, f"hallucinated content leaked back in: {term!r}"

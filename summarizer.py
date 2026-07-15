from typing import Optional

from llama_cpp import Llama

_model: Optional[Llama] = None

# Microsoft Phi-4-mini-instruct (MIT license), community GGUF quant.
_REPO_ID = "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
_FILENAME = "*Q4_K_M.gguf"

# Keep each chunk comfortably inside the model's context window (n_ctx below).
_CHUNK_CHARS = 12000


def get_model() -> Llama:
    global _model
    if _model is None:
        print("Loading Phi-4-mini-instruct summarization model (downloads on first run)…")
        _model = Llama.from_pretrained(
            repo_id=_REPO_ID,
            filename=_FILENAME,
            n_ctx=8192,
            verbose=False,
        )
        print("Summarization model ready.")
    return _model


def _complete(prompt: str, max_tokens: int = 700) -> str:
    model = get_model()
    result = model.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return result["choices"][0]["message"]["content"].strip()


def _summarize_chunk(text: str) -> str:
    # Small instruct models asked for "decisions"/"action items" against sparse
    # input will otherwise pattern-match to a generic meeting template and
    # invent plausible-sounding but fabricated content (confirmed regression:
    # a one-line test transcript produced a fully fictional product-launch
    # meeting). The explicit grounding instruction below stops that.
    prompt = (
        "You are summarizing a real meeting transcript excerpt. Base your summary "
        "STRICTLY and ONLY on information explicitly present in the transcript "
        "below. Do not invent, infer, or add any names, topics, decisions, "
        "numbers, or action items that are not explicitly stated in the text. If "
        "the excerpt does not contain enough content to identify discussion "
        "points, decisions, or action items, say so plainly instead of "
        "fabricating any.\n\n"
        "Transcript excerpt:\n"
        f'"""\n{text}\n"""\n\n'
        "Write a concise summary covering only what is actually present: key "
        "discussion points, decisions made, and action items."
    )
    return _complete(prompt)


def summarize_transcript(text: str) -> str:
    """Summarize a full meeting transcript.

    For transcripts longer than one chunk, summarizes each chunk then
    summarizes the combined chunk summaries (map-reduce) to stay within the
    model's context window.
    """
    text = text.strip()
    if not text:
        return ""

    chunks = [text[i:i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]
    chunk_summaries = [_summarize_chunk(c) for c in chunks]

    if len(chunk_summaries) == 1:
        return chunk_summaries[0]

    combined = "\n\n".join(chunk_summaries)
    prompt = (
        "The following are summaries of consecutive parts of one meeting "
        "transcript, in order. Combine them into a single coherent meeting "
        "summary: a one-paragraph overview, key discussion points, decisions "
        "made, and action items if any. Base this STRICTLY on the summaries "
        "below — do not invent or add anything not stated in them.\n\n"
        f"{combined}"
    )
    return _complete(prompt, max_tokens=900)

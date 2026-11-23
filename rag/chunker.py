"""
rag/chunker.py - Splits a long text into overlapping chunks.

Why overlap? If an important sentence sits on the border between two chunks,
the overlap makes sure it appears whole in at least one of them.
"""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into chunks of about `chunk_size` characters, where each
    chunk repeats the last `overlap` characters of the previous one.

    We try to end each chunk at a natural break (paragraph, line, sentence
    or space) so chunks don't stop in the middle of a word.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            # Look for a natural break in the last 40% of the chunk.
            search_from = start + int(chunk_size * 0.6)
            for separator in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(separator, search_from, end)
                if cut != -1:
                    end = cut + len(separator)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Step forward, keeping `overlap` characters from the previous chunk.
        start = max(end - overlap, start + 1)
    return chunks

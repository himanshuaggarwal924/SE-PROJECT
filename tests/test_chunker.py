from rag.chunker import chunk_text


def test_empty_text_gives_no_chunks():
    assert chunk_text("", 900, 150) == []


def test_short_text_is_one_chunk():
    assert chunk_text("Hello world.", 900, 150) == ["Hello world."]


def test_chunks_respect_size_and_cover_all_words():
    words = [f"word{i}" for i in range(2000)]
    text = " ".join(words)
    chunks = chunk_text(text, 900, 150)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)
    joined = " ".join(chunks)
    assert all(w in joined for w in words)


def test_consecutive_chunks_overlap():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_text(text, 300, 60)
    for first, second in zip(chunks, chunks[1:]):
        # The start of each chunk was already part of the previous one.
        assert second.split()[0] in first.split()


def test_prefers_paragraph_breaks():
    # The break at 600 is inside the last 40% of a 900-char chunk, so the
    # first chunk should end exactly at the paragraph boundary.
    para = "a" * 600
    chunks = chunk_text(f"{para}\n\n{para}", 900, 100)
    assert chunks[0] == para


def test_terminates_when_overlap_exceeds_size():
    chunks = chunk_text("x" * 50, 10, 20)
    assert chunks  # no infinite loop

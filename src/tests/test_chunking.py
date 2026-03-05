from apps.api.services.docs.chunking import chunk_text


def test_chunking_returns_chunks():
    text = "\n\n".join([f"Paragraph {i} " + ("word " * 120) for i in range(8)])
    chunks = chunk_text(text, base_metadata={"source": "simap"}, min_tokens=200, max_tokens=500)
    assert len(chunks) >= 2
    assert all("text" in c and c["text"] for c in chunks)

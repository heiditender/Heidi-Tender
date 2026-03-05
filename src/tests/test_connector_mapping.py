from apps.api.services.connectors.simap_api import SimapApiConnector


def test_normalize_publication_maps_core_fields():
    raw = {
        "id": "abc-123",
        "title": "IT Services Framework",
        "description": "Submission deadline is 2026-04-01.",
        "buyer": {"name": "City of Zurich", "location": "Zurich"},
        "cpvCodes": ["72000000", "72200000"],
        "publicationDate": "2026-03-01T10:00:00Z",
        "deadlineDate": "2026-04-01T12:00:00Z",
        "language": "en",
        "documents": [{"url": "https://example.com/a.pdf", "filename": "spec.pdf", "mimeType": "application/pdf"}],
    }
    normalized = SimapApiConnector.normalize_publication(raw)
    assert normalized["source"] == "simap"
    assert normalized["source_id"] == "abc-123"
    assert normalized["buyer_name"] == "City of Zurich"
    assert "72000000" in normalized["cpv_codes"]
    assert normalized["documents"][0]["url"] == "https://example.com/a.pdf"

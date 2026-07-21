from app.services.onboarding import default_questions


def test_single_evidence_backed_role_omits_low_information_role_question():
    questions = default_questions({"role_tracks": ["Software Engineer"]})

    assert "role_focus" not in {question["id"] for question in questions}
    assert questions[0]["id"] == "preferred_locations"


def test_multiple_role_tracks_request_explicit_priority_order():
    questions = default_questions(
        {"role_tracks": ["Software Engineer", "AI/ML Engineer"]}
    )

    assert questions[0]["id"] == "role_focus"
    assert "Software Engineer" in questions[0]["reason"]


def test_upload_request_is_rejected_before_multipart_parsing_when_too_large(
    client,
):
    limit = client.app.state.container.settings.max_upload_bytes + 512 * 1024

    response = client.post(
        "/api/onboarding/import",
        content=b"",
        headers={
            "Content-Type": "multipart/form-data; boundary=oversized",
            "Content-Length": str(limit + 1),
        },
    )

    assert response.status_code == 413
    assert "size limit" in response.json()["detail"]


def test_chunked_upload_overflow_returns_the_same_413_contract(client):
    limit = client.app.state.container.settings.max_upload_bytes + 512 * 1024
    boundary = "carivyo-stream"

    def chunks():
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="resume"; filename="resume.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        remaining = limit + 1
        block = b"x" * 64_000
        while remaining:
            current = block[:remaining]
            remaining -= len(current)
            yield current
        yield f"\r\n--{boundary}--\r\n".encode()

    response = client.post(
        "/api/onboarding/import",
        content=chunks(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413
    assert "size limit" in response.json()["detail"]

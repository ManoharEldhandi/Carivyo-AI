from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.services.resume import ResumeRunBlocked
from test_resume_approval_integrity import _create_pending_run


def test_latest_resume_run_restores_saved_work_for_the_job(client):
    run = _create_pending_run(client)

    response = client.get(f"/api/jobs/{run['job_id']}/resume-runs/latest")

    assert response.status_code == 200, response.text
    restored = response.json()["run"]
    assert restored["id"] == run["id"]
    assert restored["result"]["artifacts"]["pdf"] == run["result"]["artifacts"]["pdf"]

    client.app.state.container.database.execute(
        "UPDATE resume_runs SET status = 'failed' WHERE id = ?", (run["id"],)
    )
    ignored = client.get(f"/api/jobs/{run['job_id']}/resume-runs/latest")
    assert ignored.status_code == 200
    assert ignored.json()["run"] is None


@pytest.mark.skipif(shutil.which("tectonic") is None, reason="Tectonic is optional")
def test_tex_source_round_trip_rebuilds_exact_current_variant(client):
    run = _create_pending_run(client)
    source_response = client.get(f"/api/resume-runs/{run['id']}/source")
    assert source_response.status_code == 200, source_response.text
    source = source_response.json()
    assert source["language"] == "latex"
    assert source["editable"] is True
    assert "\\documentclass[10pt,a4paper]" in source["source"]
    assert "ResumeNavy" in source["source"]

    previous_pdf = Path(run["result"]["artifacts"]["pdf"])
    previous_source = Path(run["result"]["artifacts"]["editable_source"])
    edited = source["source"].replace("margin=0.52in", "margin=0.55in", 1)
    response = client.put(
        f"/api/resume-runs/{run['id']}/source",
        json={"source": edited, "instruction": "Increase the page margin slightly."},
    )
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["result"]["variant"] == 2
    assert revised["status"] == "needs_user_review"
    assert Path(revised["result"]["artifacts"]["pdf"]).is_file()
    assert Path(revised["result"]["artifacts"]["editable_source"]).suffix == ".tex"
    assert not previous_pdf.exists()
    assert not previous_source.exists()
    assert sorted(path.name for path in Path(revised["workspace_path"]).joinpath("variants").iterdir()) == [
        "resume2.pdf",
        "resume2.tex",
    ]

    approved = client.post(f"/api/resume-runs/{run['id']}/approve")
    assert approved.status_code == 200, approved.text


def test_tex_editor_rejects_file_and_shell_primitives(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.container.resumes,
        "_compile_tex",
        lambda source_path, pdf_path: False,
    )
    run = _create_pending_run(client)
    source = client.get(f"/api/resume-runs/{run['id']}/source").json()["source"]
    unsafe = source.replace("\\begin{document}", "\\input{/etc/passwd}\n\\begin{document}")
    response = client.put(
        f"/api/resume-runs/{run['id']}/source",
        json={"source": unsafe, "instruction": "Read another file."},
    )
    assert response.status_code == 409
    assert "blocked file or command primitive" in response.json()["detail"]

    changed_link = source.replace(
        "mailto:avery.candidate@example.com",
        "https://unapproved.example/resume-contact",
    )
    link_response = client.put(
        f"/api/resume-runs/{run['id']}/source",
        json={"source": changed_link, "instruction": "Change a hidden link target."},
    )
    assert link_response.status_code == 409
    assert "validation failed" in link_response.json()["detail"].casefold()


def test_tex_editor_rejects_unreviewed_content_changes(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.container.resumes,
        "_compile_tex",
        lambda source_path, pdf_path: False,
    )
    run = _create_pending_run(client)
    source = client.get(f"/api/resume-runs/{run['id']}/source").json()["source"]
    changed = source.replace(
        "\\end{document}",
        "Invented production ownership and unsupported revenue impact.\\par\n\\end{document}",
    )
    response = client.put(
        f"/api/resume-runs/{run['id']}/source",
        json={"source": changed, "instruction": "Add unsupported content."},
    )
    assert response.status_code == 409
    assert "formatting only" in response.json()["detail"]
    current = client.get(f"/api/resume-runs/{run['id']}").json()
    assert current["status"] == "needs_user_review"
    assert current["result"]["variant"] == 1


def test_failed_focused_revision_restores_the_previous_saved_version(client, monkeypatch):
    run = _create_pending_run(client)
    service = client.app.state.container.resumes

    def fail_generation(*args, **kwargs):
        raise ResumeRunBlocked("controlled generation failure")

    monkeypatch.setattr(service, "_generate", fail_generation)
    response = client.post(
        f"/api/resume-runs/{run['id']}/message",
        json={"message": "Emphasize API reliability."},
    )

    assert response.status_code == 409
    restored = client.get(f"/api/resume-runs/{run['id']}").json()
    assert restored["status"] == run["status"]
    assert restored["stage"] == run["stage"]
    assert restored["result"]["variant"] == 1
    assert not Path(run["workspace_path"]).joinpath("inputs", "revision-2.json").exists()


def test_tex_editor_is_disabled_when_pdf_used_the_independent_fallback(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.container.resumes,
        "_compile_tex",
        lambda source_path, pdf_path: False,
    )
    run = _create_pending_run(client)
    assert run["result"]["source_compiler"] == "reportlab_fallback"
    assert run["result"]["editable_source_exact"] is False

    source = client.get(f"/api/resume-runs/{run['id']}/source").json()
    assert source["editable"] is False
    response = client.put(
        f"/api/resume-runs/{run['id']}/source",
        json={"source": source["source"], "instruction": "Change spacing."},
    )
    assert response.status_code == 409


def test_submitted_application_locks_resume_revisions(client):
    run = _create_pending_run(client)
    client.app.state.container.database.execute(
        """
        INSERT INTO applications(
            id, job_id, resume_run_id, resume_variant, resume_pdf_hash,
            status, notes
        ) VALUES ('locked-application', ?, ?, ?, ?, 'applied', '')
        """,
        (
            run["job_id"],
            run["id"],
            run["result"]["variant"],
            run["result"]["provenance"]["pdf_hash"],
        ),
    )

    response = client.post(
        f"/api/resume-runs/{run['id']}/message",
        json={"message": "Change this submitted resume."},
    )
    assert response.status_code == 409
    assert "submitted application" in response.json()["detail"]


def test_enhancv_adapter_requires_consent_and_keeps_only_compact_final_report(
    client,
    tmp_path: Path,
):
    run = _create_pending_run(client)
    fake = tmp_path / "enhancv_checker.py"
    fake.write_text(
        """
import argparse, json, os
from pathlib import Path
p=argparse.ArgumentParser()
for name in ('repo','pdf','job-description-file','out','json','html','screenshot','profile','email-env','password-env'):
    p.add_argument('--'+name)
p.add_argument('--no-keychain', action='store_true')
p.add_argument('--headless', action='store_true')
p.add_argument('--headed', action='store_true')
a=p.parse_args()
Path(a.out).write_text(
  'Your Score\\n88 / 100\\nTAILORING\\n91%\\n' +
  os.environ.get('CARIVYO_ENHANCV_EMAIL', '') + '\\n' +
  os.environ.get('CARIVYO_ENHANCV_PASSWORD', ''),
  encoding='utf-8'
)
Path(a.json).write_text(json.dumps({
  'ok': True, 'mode': 'jd-tailored', 'score': 88, 'tailoredScore': 88,
  'genericScore': 82,
  'sections': {'content': '90', 'secret': os.environ.get('CARIVYO_ENHANCV_EMAIL', '')},
  'tailoring': {'applied': True, 'nested': [os.environ.get('CARIVYO_ENHANCV_PASSWORD', '')]}
}), encoding='utf-8')
Path(a.html).write_text('<html>temporary</html>', encoding='utf-8')
Path(a.screenshot).write_bytes(b'temporary')
""".strip(),
        encoding="utf-8",
    )
    settings = client.app.state.container.settings
    settings.enhancv_script_path = fake
    settings.enhancv_playwright_repo = settings.project_root / "frontend"
    settings.enhancv_email = "authorized@example.com"
    settings.enhancv_password = SecretStr("not-returned-or-logged")
    settings.enhancv_headless = True

    engines = client.get("/api/ats/engines")
    assert engines.status_code == 200
    enhancv = next(item for item in engines.json()["engines"] if item["id"] == "enhancv")
    assert enhancv["available"] is True

    denied = client.post(
        f"/api/resume-runs/{run['id']}/ats-reports/enhancv",
        json={"confirmed_external_processing": False},
    )
    assert denied.status_code == 422

    started = client.post(
        f"/api/resume-runs/{run['id']}/ats-reports/enhancv",
        json={"confirmed_external_processing": True},
    )
    assert started.status_code == 200, started.text
    latest = client.get(
        f"/api/resume-runs/{run['id']}/ats-reports/enhancv"
    ).json()["report"]
    assert latest["status"] == "complete"
    assert latest["score"] == 88
    assert latest["report"]["mode"] == "jd-tailored"
    serialized = json.dumps(latest)
    assert "not-returned-or-logged" not in serialized
    assert "authorized@example.com" not in serialized
    assert [path.name for path in settings.runtime_dir.glob("enhancv-*")] == [
        "enhancv-browser-profile"
    ]

    final_path = Path(run["workspace_path"]) / "reports" / "enhancv-final.json"
    assert final_path.is_file()
    final = json.loads(final_path.read_text(encoding="utf-8"))
    assert final["score"] == 88
    assert not (Path(run["workspace_path"]) / "reports" / "report.html").exists()

    service = client.app.state.container.enhancv
    report = service.start(run["id"])
    result_path = Path(run["result_path"])
    changed_result = json.loads(result_path.read_text(encoding="utf-8"))
    changed_result["variant"] += 1
    result_path.write_text(json.dumps(changed_result), encoding="utf-8")
    service.execute(report["id"])
    rejected = service.get(report["id"])
    assert rejected["status"] == "failed"
    assert "changed after consent" in rejected["error"]
    assert not final_path.exists()

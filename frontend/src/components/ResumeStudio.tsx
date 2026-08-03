import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Code2,
  Download,
  FileJson2,
  FilePenLine,
  Gauge,
  Info,
  LoaderCircle,
  MinusCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X
} from "lucide-react";
import { api } from "../api";
import { useModalDialog } from "../hooks/useModalDialog";
import type {
  ATSCheck,
  ATSEngine,
  ATSSemanticReview,
  ExternalATSReport,
  Job,
  ResumeRun,
  ResumeSource
} from "../types";

interface Props {
  job: Job;
  onClose: () => void;
}

interface BoundPreview {
  runId: string;
  variant: number;
  url: string;
  loaded: boolean;
}

interface BoundSemanticReview {
  runId: string;
  variant: number;
  review: ATSSemanticReview;
}

export function ResumeStudio({ job, onClose }: Props) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [instructions, setInstructions] = useState(
    "Keep it concise, preserve my strongest evidence, and emphasize the requirements I can prove."
  );
  const [revision, setRevision] = useState("");
  const [run, setRun] = useState<ResumeRun | null>(null);
  const [preview, setPreview] = useState<BoundPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [isRevising, setIsRevising] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [semanticConsent, setSemanticConsent] = useState(false);
  const [atsEngine, setAtsEngine] = useState<"local" | "enhancv">("local");
  const [atsEngines, setAtsEngines] = useState<ATSEngine[]>([]);
  const [externalConsent, setExternalConsent] = useState(false);
  const [externalReport, setExternalReport] = useState<ExternalATSReport | null>(null);
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);
  const [sourceEditorOpen, setSourceEditorOpen] = useState(false);
  const [resumeSource, setResumeSource] = useState<ResumeSource | null>(null);
  const [sourceDraft, setSourceDraft] = useState("");
  const [sourceInstruction, setSourceInstruction] = useState("Formatting-only TeX adjustment");
  const [restoringRun, setRestoringRun] = useState(true);
  const [boundSemanticReview, setBoundSemanticReview] =
    useState<BoundSemanticReview | null>(null);
  const currentRunVariantKey = run ? runVariantKey(run.id, run.result.variant) : "";
  const currentRunVariantKeyRef = useRef(currentRunVariantKey);
  currentRunVariantKeyRef.current = currentRunVariantKey;

  const currentPreview =
    run && preview && isBoundToRun(preview, run) ? preview : null;
  const previewLoaded = currentPreview?.loaded === true;
  const semanticReview =
    run && boundSemanticReview && isBoundToRun(boundSemanticReview, run)
      ? boundSemanticReview.review
      : null;

  useModalDialog(true, dialogRef, closeRef, onClose);

  useEffect(() => {
    let active = true;
    void api.atsEngines().then((payload) => {
      if (active) setAtsEngines(payload.engines);
    }).catch(() => {
      if (active) setAtsEngines([]);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setRestoringRun(true);
    void api.latestResumeRun(job.id)
      .then((payload) => {
        if (active && payload.run) setRun(payload.run);
      })
      .catch((caught) => {
        if (active) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Saved resume work could not be restored."
          );
        }
      })
      .finally(() => {
        if (active) setRestoringRun(false);
      });
    return () => { active = false; };
  }, [job.id]);

  useEffect(() => {
    setExternalConsent(false);
    setExternalReport(null);
    setRiskAcknowledged(false);
  }, [run?.id, run?.result?.variant]);

  useEffect(() => {
    if (!run || externalReport?.status !== "running") return;
    const runId = run.id;
    const timer = window.setInterval(() => {
      void api.enhancvReport(runId).then((payload) => {
        if (payload.report) setExternalReport(payload.report);
      }).catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Enhancv status could not refresh.");
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [externalReport?.status, run]);

  useEffect(() => {
    if (run && document.activeElement === document.body) {
      closeRef.current?.focus();
    }
  }, [run]);

  useEffect(() => {
    if (!run?.result?.artifacts?.render || isRevising) {
      setPreview(null);
      return;
    }
    const runId = run.id;
    const variant = run.result.variant;
    let active = true;
    let objectUrl = "";
    setPreview(null);
    void api
      .artifact(runId, "render")
      .then((blob) => {
        const nextObjectUrl = URL.createObjectURL(blob);
        if (!active) {
          URL.revokeObjectURL(nextObjectUrl);
          return;
        }
        objectUrl = nextObjectUrl;
        setPreview({ runId, variant, url: objectUrl, loaded: false });
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Preview could not load.");
        }
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [isRevising, run?.id, run?.result?.artifacts?.render, run?.result?.variant]);

  const atsIssues = useMemo(
    () =>
      run?.result.ats_analysis.checks.filter(
        (check) => check.status === "fail" || check.status === "warning"
      ) ?? [],
    [run]
  );
  const priorityActions = run?.result.ats_analysis.report_summary?.priority_actions ??
    atsIssues.slice(0, 5).map((check) => ({
      check_id: check.id,
      label: check.label,
      severity: check.status === "fail" ? "fail" as const : "warning" as const,
      evidence: check.evidence,
      suggestion: check.suggestion
    }));
  const enhancvEngine = atsEngines.find((engine) => engine.id === "enhancv");
  const assessment = run?.result.ats_analysis.assessment;
  const perspectives = assessment
    ? [assessment.compatibility, assessment.evidence_alignment, assessment.content_quality]
    : [];
  const structuredRequirements = run?.result.ats_analysis.structured_alignment?.requirements ?? [];
  const unresolvedRequirements = structuredRequirements.filter(
    (item) => item.match_status === "unsupported" || item.match_status === "listed_only"
  );
  const requiresRiskAcknowledgement = Boolean(
    run &&
      run.status !== "ready_to_apply" &&
      (assessment?.status === "blocked" ||
        assessment?.status === "needs_focus" ||
        unresolvedRequirements.length > 0 ||
        atsIssues.length > 0)
  );

  async function create() {
    setBusy(true);
    setError("");
    try {
      setRun(await api.createResume(job.id, instructions));
      setExternalReport(null);
      setResumeSource(null);
      setSourceEditorOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Resume generation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function revise() {
    if (!run || !revision.trim()) return;
    setIsRevising(true);
    setPreview(null);
    setBoundSemanticReview(null);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setRun(await api.reviseResume(run.id, revision.trim()));
      setRevision("");
      setExternalReport(null);
      setResumeSource(null);
      setSourceEditorOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Revision could not be applied.");
    } finally {
      setIsRevising(false);
      setBusy(false);
    }
  }

  async function approve() {
    if (!run) return;
    if (!previewLoaded) {
      setError("Wait for the current resume preview to load before approving it.");
      return;
    }
    if (requiresRiskAcknowledgement && !riskAcknowledged) {
      setError("Review and acknowledge the unresolved requirements and priority actions before approval.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setRun(await api.approveResume(run.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Approval could not be recorded.");
    } finally {
      setBusy(false);
    }
  }

  async function applyWithResume() {
    if (!run) return;
    let applicationTab: Window | null = null;
    try {
      applicationTab = window.open("about:blank", "_blank");
    } catch {
      applicationTab = null;
    }
    if (!applicationTab) {
      setNotice("");
      setError(
        "Your browser blocked the official application tab. Allow pop-ups for Carivyo, then try again."
      );
      return;
    }
    try {
      applicationTab.opener = null;
    } catch {
      try {
        if (!applicationTab.closed) applicationTab.close();
      } catch {
        // Continue with the explicit failure state even if the tab cannot be closed.
      }
      setNotice("");
      setError("The official application tab could not be opened securely. Please try again.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.prepareApplication(job.id, run.id);
      const response = await api.openApply(job.id);
      const officialUrl = safeOfficialUrl(response.official_url);
      if (!officialUrl) {
        throw new Error("The official application URL was invalid or unsafe.");
      }

      applicationTab.location.replace(officialUrl);
      setNotice(
        "The official application opened in a new tab. This approved resume is attached to the local application record; review and submit the form yourself."
      );
    } catch (caught) {
      try {
        if (!applicationTab.closed) applicationTab.close();
      } catch {
        // The error below remains the authoritative handoff status.
      }
      setError(
        caught instanceof Error ? caught.message : "The official application could not open."
      );
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!run) return;
    try {
      const blob = await api.artifact(run.id, "pdf");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = run.result.export_filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download failed.");
    }
  }

  async function downloadAtsReport() {
    if (!run) return;
    try {
      const blob = await api.artifact(run.id, "ats");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${job.company}-${job.title}-ats-analysis.json`.replaceAll(" ", "-");
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "ATS report download failed.");
    }
  }

  async function openSourceEditor() {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      const source = await api.resumeSource(run.id);
      setResumeSource(source);
      setSourceDraft(source.source);
      setSourceEditorOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "TeX source could not load.");
    } finally {
      setBusy(false);
    }
  }

  async function saveSource() {
    if (!run || !resumeSource || !sourceDraft.trim()) return;
    setBusy(true);
    setIsRevising(true);
    setPreview(null);
    setError("");
    setNotice("");
    try {
      const next = await api.updateResumeSource(
        run.id,
        sourceDraft,
        sourceInstruction.trim() || "Manual TeX edit"
      );
      setRun(next);
      setResumeSource(null);
      setSourceEditorOpen(false);
      setExternalReport(null);
      setNotice("TeX compiled and the current PDF and ATS report were rebuilt.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "TeX could not be rebuilt.");
    } finally {
      setIsRevising(false);
      setBusy(false);
    }
  }

  async function downloadSource() {
    if (!run) return;
    try {
      const blob = await api.artifact(run.id, "source");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = resumeSource?.filename || `${job.company}-${job.title}.tex`.replaceAll(" ", "-");
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "TeX download failed.");
    }
  }

  async function runEnhancv() {
    if (!run) return;
    setBusy(true);
    setError("");
    setExternalReport(null);
    try {
      const report = await api.createEnhancvReport(run.id, externalConsent);
      setExternalReport(report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Enhancv report could not start.");
    } finally {
      setBusy(false);
    }
  }

  async function runSemanticReview() {
    if (!run) return;
    const runId = run.id;
    const variant = run.result.variant;
    const requestKey = runVariantKey(runId, variant);
    setBusy(true);
    setError("");
    setBoundSemanticReview(null);
    try {
      const review = await api.createAtsSemanticReview(runId, semanticConsent);
      if (currentRunVariantKeyRef.current !== requestKey) return;
      if (review.run_id !== runId) {
        setError("The semantic review did not match the current resume version.");
        return;
      }
      setBoundSemanticReview({ runId, variant, review });
      if (review.status === "failed") {
        setError(review.error || "The optional AI-assisted review was unavailable.");
      }
    } catch (caught) {
      if (currentRunVariantKeyRef.current === requestKey) {
        setError(caught instanceof Error ? caught.message : "Semantic review could not run.");
      }
    } finally {
      setBusy(false);
    }
  }

  function markPreviewLoaded() {
    if (!run || !currentPreview) return;
    const { runId, variant, url } = currentPreview;
    setPreview((candidate) =>
      candidate &&
      candidate.runId === runId &&
      candidate.variant === variant &&
      candidate.url === url
        ? { ...candidate, loaded: true }
        : candidate
    );
  }

  function markPreviewFailed() {
    if (!run || !currentPreview) return;
    const { runId, variant, url } = currentPreview;
    if (currentRunVariantKeyRef.current !== runVariantKey(runId, variant)) return;
    setPreview((candidate) =>
      candidate &&
      candidate.runId === runId &&
      candidate.variant === variant &&
      candidate.url === url
        ? { ...candidate, loaded: false }
        : candidate
    );
    setError("The current resume preview could not be displayed.");
  }

  function startNewVersion() {
    setRun(null);
    setPreview(null);
    setResumeSource(null);
    setSourceEditorOpen(false);
    setExternalReport(null);
    setBoundSemanticReview(null);
    setError("");
    setNotice("");
  }

  return (
    <div className="modal-backdrop">
      <section
        ref={dialogRef}
        className="resume-studio"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resume-studio-title"
        tabIndex={-1}
      >
        <header className="resume-studio__header">
          <div className="resume-studio__identity">
            <span className="assistant-identity__mark"><FilePenLine aria-hidden="true" /></span>
            <div>
              <p className="eyebrow">Resume Studio</p>
              <h2 id="resume-studio-title">{job.title}</h2>
              <span>{job.company} · official job</span>
            </div>
          </div>
          <div className="resume-stage" aria-label="Resume workflow progress">
            <span className="is-complete"><Check aria-hidden="true" /> Evidence</span>
            <span className={run ? "is-complete" : "is-active"}>2 Design</span>
            <span className={run?.status === "ready_to_apply" ? "is-complete" : run ? "is-active" : ""}>
              3 Review
            </span>
          </div>
          <button
            ref={closeRef}
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="Close resume studio"
          >
            <X aria-hidden="true" />
          </button>
        </header>

        {restoringRun ? (
          <div className="loading-panel" role="status">
            <LoaderCircle className="spin" aria-hidden="true" />
            Loading saved resume…
          </div>
        ) : !run ? (
          <div className="resume-start">
            <div className="resume-start__intro">
              <span className="resume-start__icon"><Sparkles aria-hidden="true" /></span>
              <div>
                <h3>Tailor your resume for this job</h3>
                <p>Only confirmed evidence can be used.</p>
              </div>
            </div>

            <div className="resume-start__grid">
              <div className="instruction-card">
                <label htmlFor="resume-instructions">What should this version prioritize?</label>
                <textarea
                  id="resume-instructions"
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                  rows={7}
                  placeholder="Preserve the current tone, emphasize backend APIs, and keep it to one page."
                  disabled={busy}
                />
                <span>Natural language is fine. Truth and validation rules always win.</span>
              </div>
              <div className="resume-guardrails">
                <p className="eyebrow">Built-in guardrails</p>
                {[
                  "Approved evidence only",
                  "Every recognized source section preserved",
                  "Local hiring-manager review when Ollama is available",
                  "Original resume never overwritten",
                  "Unsupported requirements stay visible",
                  "PDF, links, layout, and extraction validated"
                ].map((item) => (
                  <div key={item}><CheckCircle2 aria-hidden="true" /> {item}</div>
                ))}
                <div className="truth-callout">
                  <ShieldCheck aria-hidden="true" />
                  Fabricated metrics, hidden keywords, and inflated ownership are rejected.
                </div>
              </div>
            </div>

            <button
              className="button button--primary resume-start__action"
              type="button"
              onClick={() => void create()}
              disabled={busy}
            >
              {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
              Create tailored resume
            </button>
          </div>
        ) : (
          <>
            <div className="resume-summary">
              <div aria-label={`Resume draft ${run.result.variant}`}>
                <span>Draft</span>
                <strong>{run.result.variant}</strong>
                <small>{run.result.mode.replaceAll("_", " ")}</small>
              </div>
              <div>
                <span>JD confidence</span>
                <strong>{run.result.ats_analysis.jd_quality?.confidence ?? "unknown"}</strong>
                <small>{run.result.ats_analysis.jd_quality?.requirement_count ?? 0} requirements parsed</small>
              </div>
              <div>
                <span>Compatibility</span>
                <strong>{assessment?.compatibility.score === null || assessment?.compatibility.score === undefined ? "—" : `${Math.round(assessment.compatibility.score)}%`}</strong>
                <small>{assessment?.compatibility.status?.replaceAll("_", " ") ?? "not assessed"}</small>
              </div>
              <div className={(unresolvedRequirements.length) ? "has-warning" : "is-positive"}>
                <span>Evidence alignment</span>
                <strong>{assessment?.evidence_alignment.score === null || assessment?.evidence_alignment.score === undefined ? "—" : `${Math.round(assessment.evidence_alignment.score)}%`}</strong>
                <small>{unresolvedRequirements.length} unresolved requirements</small>
              </div>
              <div className={atsIssues.length ? "has-warning" : "is-positive"}>
                <span>Content review</span>
                <strong>{assessment?.content_quality.score === null || assessment?.content_quality.score === undefined ? "—" : `${Math.round(assessment.content_quality.score)}%`}</strong>
                <small>{atsIssues.length} exact actions</small>
              </div>
            </div>

            <div className="resume-grid">
              <section className="resume-pane resume-pane--preview" aria-labelledby="preview-title">
                <div className="pane-heading">
                  <div>
                    <h3 id="preview-title">Resume preview</h3>
                  </div>
                  <div className="resume-source-actions">
                    <button
                      className="button button--quiet"
                      type="button"
                      onClick={startNewVersion}
                      disabled={busy}
                    >
                      <FilePenLine aria-hidden="true" /> New version
                    </button>
                    <button
                      className="button button--quiet"
                      type="button"
                      onClick={() => void openSourceEditor()}
                      disabled={
                        busy ||
                        run.result.variant >= 4 ||
                        run.result.editable_source_exact !== true
                      }
                      title={
                        run.result.editable_source_exact === true
                          ? "Edit formatting in the compiled TeX source"
                          : "Install Tectonic and create a new version to enable exact TeX editing"
                      }
                    >
                      <Code2 aria-hidden="true" /> Edit TeX
                    </button>
                    <button
                      className="button button--quiet"
                      type="button"
                      onClick={() => void download()}
                    >
                      <Download aria-hidden="true" /> {run.status === "ready_to_apply" ? "PDF" : "Draft PDF"}
                    </button>
                  </div>
                </div>
                <div
                  className="resume-preview-shell"
                  role="region"
                  aria-label="Scrollable resume preview"
                  tabIndex={0}
                >
                  {currentPreview ? (
                    <img
                      className="resume-preview"
                      src={currentPreview.url}
                      alt={`Rendered resume preview for ${job.title} at ${job.company}`}
                      onLoad={markPreviewLoaded}
                      onError={markPreviewFailed}
                    />
                  ) : (
                    <div className="loading-panel">
                      <LoaderCircle className="spin" aria-hidden="true" />
                      Preparing preview…
                    </div>
                  )}
                </div>
              </section>

              <section className="resume-pane resume-pane--review" aria-labelledby="review-title">
                <div className="pane-heading">
                  <div>
                    <h3 id="review-title">Review and approve</h3>
                  </div>
                  <span className={`review-status review-status--${run.status}`}>
                    {run.status === "ready_to_apply" ? <Check aria-hidden="true" /> : null}
                    {run.status === "ready_to_apply" ? "Approved" : "Review required"}
                  </span>
                </div>

                {run.status !== "ready_to_apply" ? (
                  <div className="review-actions review-actions--primary">
                    {requiresRiskAcknowledgement ? (
                      <label className="risk-acknowledgement">
                        <input
                          type="checkbox"
                          checked={riskAcknowledged}
                          onChange={(event) => setRiskAcknowledged(event.target.checked)}
                        />
                        <span>
                          <strong>I reviewed the unresolved risks</strong>
                          <small>Visible gaps remain truthful and will not be silently treated as matches.</small>
                        </span>
                      </label>
                    ) : null}
                    <button
                      className="button button--primary button--wide"
                      type="button"
                      onClick={() => void approve()}
                      disabled={busy || !previewLoaded || (requiresRiskAcknowledgement && !riskAcknowledged)}
                      title={previewLoaded ? undefined : "Wait for the current preview to load"}
                    >
                      {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Check aria-hidden="true" />}
                      Approve resume
                    </button>
                    <label htmlFor="resume-revision">Request changes</label>
                    <div className="revision-box">
                      <textarea
                        id="resume-revision"
                        value={revision}
                        onChange={(event) => setRevision(event.target.value)}
                        rows={3}
                        placeholder="Move the strongest relevant project higher without changing its claims."
                      />
                      <button
                        className="button button--secondary"
                        type="button"
                        onClick={() => void revise()}
                        disabled={busy || !revision.trim() || run.result.variant >= 4}
                      >
                        <RefreshCw aria-hidden="true" /> Revise
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="resume-ready-actions">
                    <div className="resume-ready-message">
                      <CheckCircle2 aria-hidden="true" />
                      <span><strong>Approved and ready.</strong> Submission remains under your control.</span>
                    </div>
                    <button className="button button--secondary" type="button" onClick={() => void download()}>
                      <Download aria-hidden="true" /> Download PDF
                    </button>
                    <button
                      className="button button--primary"
                      type="button"
                      onClick={() => void applyWithResume()}
                      disabled={busy}
                    >
                      Open official application <ArrowUpRight aria-hidden="true" />
                    </button>
                  </div>
                )}

                {sourceEditorOpen && resumeSource ? (
                  <section className="tex-editor" aria-labelledby="tex-editor-title">
                    <div className="tex-editor__heading">
                      <div>
                        <p className="eyebrow">Editable source</p>
                        <h4 id="tex-editor-title">{resumeSource.filename}</h4>
                      </div>
                      <button className="button button--quiet" type="button" onClick={() => void downloadSource()}>
                        <Download aria-hidden="true" /> TeX
                      </button>
                    </div>
                    <label htmlFor="tex-source">TeX code</label>
                    <textarea
                      id="tex-source"
                      className="tex-editor__code"
                      value={sourceDraft}
                      onChange={(event) => setSourceDraft(event.target.value)}
                      rows={18}
                      spellCheck={false}
                      disabled={busy}
                    />
                    <label htmlFor="tex-edit-note">What did you change?</label>
                    <input
                      id="tex-edit-note"
                      value={sourceInstruction}
                      onChange={(event) => setSourceInstruction(event.target.value)}
                      maxLength={1000}
                      disabled={busy}
                    />
                    <p className="muted">
                      Formatting edits are allowed. Use Request changes for factual wording; unsupported content and unsafe TeX commands are rejected.
                    </p>
                    <div className="tex-editor__actions">
                      <button className="button button--quiet" type="button" onClick={() => setSourceEditorOpen(false)} disabled={busy}>
                        Cancel
                      </button>
                      <button className="button button--primary" type="button" onClick={() => void saveSource()} disabled={busy || sourceDraft === resumeSource.source}>
                        {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
                        Compile and rebuild
                      </button>
                    </div>
                  </section>
                ) : null}

                <section className="analysis-command-center" aria-labelledby="analysis-command-title">
                  <div className="analysis-command-center__heading">
                    <div>
                      <p className="eyebrow">ATS v2 · decision workspace</p>
                      <h4 id="analysis-command-title">What is proven, missing, and worth fixing</h4>
                    </div>
                    <span className={`assessment-state assessment-state--${assessment?.status ?? "unknown"}`}>
                      {assessment?.status?.replaceAll("_", " ") ?? "analysis unavailable"}
                    </span>
                  </div>

                  <div className={`jd-confidence jd-confidence--${run.result.ats_analysis.jd_quality?.status ?? "unknown"}`}>
                    <ShieldCheck aria-hidden="true" />
                    <div>
                      <strong>
                        Job description {run.result.ats_analysis.jd_quality?.status ?? "not classified"} · {run.result.ats_analysis.jd_quality?.confidence ?? "unknown"} confidence
                      </strong>
                      <span>{run.result.ats_analysis.jd_quality?.reason ?? "A complete official description is required for job-specific alignment."}</span>
                    </div>
                  </div>

                  <div className="perspective-grid">
                    {perspectives.map((perspective) => (
                      <article key={perspective.id} className={`perspective-card perspective-card--${perspective.status}`}>
                        <span>{perspective.label}</span>
                        <strong>{perspective.score === null ? "Not scored" : `${Math.round(perspective.score ?? 0)}%`}</strong>
                        <small>{perspective.status.replaceAll("_", " ")}</small>
                      </article>
                    ))}
                  </div>

                  <div className="analysis-worklist">
                    <div>
                      <span className="field-label">Exact priority actions</span>
                      {priorityActions.length ? (
                        <ol>
                          {priorityActions.map((action) => (
                            <li key={action.check_id}>
                              <strong>{action.label}</strong>
                              <span>{action.suggestion}</span>
                            </li>
                          ))}
                        </ol>
                      ) : <p className="muted">No deterministic action is required.</p>}
                    </div>
                    <div>
                      <span className="field-label">Required and preferred gaps</span>
                      {unresolvedRequirements.length ? (
                        <ul>
                          {unresolvedRequirements.slice(0, 8).map((item) => (
                            <li key={item.id}>
                              <strong>{item.priority}</strong>
                              <span>{item.text}</span>
                              <small>{item.match_status?.replaceAll("_", " ")}</small>
                            </li>
                          ))}
                        </ul>
                      ) : <p className="muted">No structured requirement gap was detected.</p>}
                    </div>
                  </div>
                </section>

                <details className="resume-supporting-details">
                  <summary>Why this resume matches</summary>
                  <div className="resume-supporting-details__body">
                    {(["direct", "transferable", "unsupported", "unclear"] as const).map(
                      (kind) =>
                        run.result.coverage[kind]?.length ? (
                          <div className="coverage-group" key={kind}>
                            <h4>{kind}</h4>
                            {run.result.coverage[kind].map((item) => (
                              <div className={`coverage-item coverage-item--${kind}`} key={item.requirement}>
                                <span>{item.requirement}</span>
                                <small>
                                  {item.evidence_ids.length
                                    ? `${item.evidence_ids.length} approved evidence links`
                                    : "No approved evidence"}
                                </small>
                              </div>
                            ))}
                          </div>
                        ) : null
                    )}
                  </div>
                </details>

                <details className="resume-supporting-details">
                  <summary>Sections and local hiring-manager review</summary>
                  <div className="resume-supporting-details__body">
                    <h4>Section completeness</h4>
                    <div className="validation-list">
                      {(run.result.section_inventory ?? []).map((section) => (
                        <div className={section.present ? "is-passed" : "is-warning"} key={section.id}>
                          {section.present
                            ? <CheckCircle2 aria-hidden="true" />
                            : <AlertTriangle aria-hidden="true" />}
                          <span>{section.label}</span>
                          <strong>{section.present ? `${section.claim_count} items` : "Missing"}</strong>
                        </div>
                      ))}
                    </div>

                    {run.result.hiring_evaluation?.status === "complete" ? (
                      <div className="ats-report">
                        <div className="ats-report__heading">
                          <div>
                            <p className="eyebrow">On-device decision support</p>
                            <h4>Hiring-manager lens</h4>
                          </div>
                          <strong>{run.result.hiring_evaluation.verdict?.replaceAll("_", " ") ?? "Advisory"}</strong>
                        </div>
                        <p className="muted">
                          {run.result.hiring_evaluation.disclaimer}
                        </p>
                        {run.result.hiring_evaluation.score_basis ? (
                          <p className="muted">
                            {run.result.hiring_evaluation.score_basis}.
                          </p>
                        ) : null}
                        <div className="ats-categories">
                          {run.result.hiring_evaluation.dimensions.map((dimension) => (
                            <div key={dimension.id}>
                              <span>{dimension.id.replaceAll("_", " ")}</span>
                              <strong>{Math.round(dimension.score)}/{dimension.max}</strong>
                              <span className="ats-category-track" aria-hidden="true">
                                <span style={{ width: `${(dimension.score / dimension.max) * 100}%` }} />
                              </span>
                              <small>{dimension.rationale}</small>
                            </div>
                          ))}
                        </div>
                        {run.result.hiring_evaluation.recommended_changes.length ? (
                          <div className="ats-issues">
                            <span className="field-label">Recommended truthful improvements</span>
                            <ul className="detail-list">
                              {run.result.hiring_evaluation.recommended_changes.map((change) => (
                                <li key={change}>{change}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        <p className="mono">
                          {run.result.hiring_evaluation.provider} · {run.result.hiring_evaluation.model}
                        </p>
                      </div>
                    ) : (
                      <div className="inline-notice">
                        {run.result.hiring_evaluation?.reason ??
                          "The local hiring-manager review was not run for this saved version."}
                      </div>
                    )}
                  </div>
                </details>

                <details className="resume-supporting-details">
                  <summary>Resume checks (27)</summary>
                  <div className="resume-supporting-details__body">
                <h4>Automated checks</h4>
                {run.result.base_selection ? (
                  <div className="base-choice">
                    <ShieldCheck aria-hidden="true" />
                    <div>
                      <span>Best evidence-backed base selected</span>
                      <p>{run.result.base_selection.rationale[0]}</p>
                    </div>
                  </div>
                ) : null}
                <div className="validation-list">
                  {VALIDATION_CHECKS.map(({ key, label }) => {
                    const value = run.result.validation[key];
                    const passed = validationPassed(key, value);
                    return (
                      <div className={passed ? "is-passed" : "is-warning"} key={key}>
                        {passed
                          ? <CheckCircle2 aria-hidden="true" />
                          : <AlertTriangle aria-hidden="true" />}
                        <span>{label}</span>
                        <strong>{humanizeValidationValue(key, value)}</strong>
                      </div>
                    );
                  })}
                </div>
                <details className="secondary-disclosure">
                  <summary>About these checks</summary>
                  <p>Automated checks cannot replace your review. Inspect the preview before approval.</p>
                </details>

                <div className="ats-report" aria-labelledby="ats-report-title">
                  <div className="ats-report__heading">
                    <div>
                      <p className="eyebrow">27 checks</p>
                      <h4 id="ats-report-title">Detailed submission checks</h4>
                    </div>
                    <div className="ats-engine-toggle" role="radiogroup" aria-label="ATS report engine">
                      <button
                        type="button"
                        role="radio"
                        aria-checked={atsEngine === "local"}
                        className={atsEngine === "local" ? "is-selected" : ""}
                        onClick={() => setAtsEngine("local")}
                      >
                        Local
                      </button>
                      <button
                        type="button"
                        role="radio"
                        aria-checked={atsEngine === "enhancv"}
                        className={atsEngine === "enhancv" ? "is-selected" : ""}
                        onClick={() => setAtsEngine("enhancv")}
                      >
                        Enhancv
                      </button>
                    </div>
                  </div>

                  <div hidden={atsEngine !== "local"}>
                    <div className="ats-report__utility">
                      <span>Runs locally on the exact PDF and job description.</span>
                      <button className="button button--quiet" type="button" onClick={() => void downloadAtsReport()}>
                        <FileJson2 aria-hidden="true" /> JSON
                      </button>
                    </div>

                  <div className="perspective-grid perspective-grid--report" aria-label="Independent ATS perspectives">
                    {perspectives.map((perspective) => (
                      <article key={perspective.id} className={`perspective-card perspective-card--${perspective.status}`}>
                        <span>{perspective.label}</span>
                        <strong>{perspective.score === null ? "Not scored" : `${Math.round(perspective.score ?? 0)}%`}</strong>
                        <small>{perspective.status.replaceAll("_", " ")}</small>
                      </article>
                    ))}
                  </div>
                  <p className="muted">
                    {assessment?.explanation ?? "Compatibility, evidence alignment, and content quality are reviewed independently."}
                    {` Parser consensus: ${Math.round(run.result.ats_analysis.parse_rate)}%.`}
                  </p>

                  {atsIssues.length ? (
                    <div className="ats-issues">
                      <span className="field-label">Highest-value fixes</span>
                      {atsIssues.slice(0, 5).map((check) => (
                        <ATSCheckRow check={check} key={check.id} />
                      ))}
                      {atsIssues.length > 5 ? (
                        <details>
                          <summary>{atsIssues.length - 5} more checks need attention</summary>
                          {atsIssues.slice(5).map((check) => (
                            <ATSCheckRow check={check} key={check.id} />
                          ))}
                        </details>
                      ) : null}
                    </div>
                  ) : (
                    <div className="ats-all-clear">
                      <CheckCircle2 aria-hidden="true" />
                      No deterministic checks require attention.
                    </div>
                  )}

                  <details className="ats-methodology">
                    <summary><Info aria-hidden="true" /> How to read this report</summary>
                    <p>{run.result.ats_analysis.disclaimer}</p>
                    <p>{run.result.ats_analysis.protected_trait_policy}</p>
                    <p className="mono">Analyzer {run.result.ats_analysis.analyzer_version}</p>
                  </details>


                  <div className="semantic-review">
                    <div>
                      <p className="eyebrow">Optional AI-assisted review</p>
                      <h4>Check claims against the job</h4>
                      <p>
                        Uses the selected AI runtime only when you ask. It cannot change
                        the deterministic score, readiness, or approval gate.
                      </p>
                    </div>
                    {!semanticReview ? (
                      <div>
                        <label className="semantic-consent">
                          <input
                            type="checkbox"
                            checked={semanticConsent}
                            onChange={(event) => setSemanticConsent(event.target.checked)}
                            disabled={busy}
                          />
                          <span>
                            I understand this processes the full extracted resume and job
                            description. Ollama stays on device; provider models process them
                            through the selected CLI.
                          </span>
                        </label>
                        <button
                          className="button button--secondary"
                          type="button"
                          onClick={() => void runSemanticReview()}
                          disabled={busy || !semanticConsent}
                        >
                          {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
                          Check with AI
                        </button>
                      </div>
                    ) : semanticReview.status === "complete" && semanticReview.response ? (
                      <div className="semantic-review__result">
                        <p className="muted">
                          AI-assisted · {semanticReview.provider} · {semanticReview.model} · {semanticReview.usage.input_tokens + semanticReview.usage.output_tokens} {semanticReview.usage.kind} tokens
                        </p>
                        {semanticReview.response.findings.length ? (
                          semanticReview.response.findings.map((finding, index) => (
                            <details key={`${finding.category}-${index}`}>
                              <summary>
                                <span>{finding.claim}</span>
                                <strong>{finding.evidence_verification.status}</strong>
                              </summary>
                              <p><strong>Recommendation:</strong> {finding.recommendation}</p>
                              <p><strong>Resume evidence:</strong> {finding.resume_evidence}</p>
                              <p><strong>JD evidence:</strong> {finding.jd_evidence}</p>
                            </details>
                          ))
                        ) : (
                          <p>No additional evidence-bound semantic findings were returned.</p>
                        )}
                        <small>{semanticReview.response.disclaimer}</small>
                      </div>
                    ) : (
                      <div className="inline-error" role="status">
                        {semanticReview.error || "The optional semantic review was unavailable."}
                      </div>
                    )}
                  </div>
                  </div>

                  {atsEngine === "enhancv" ? (
                    <div className="enhancv-panel">
                      <div className="enhancv-panel__intro">
                        <div>
                          <h4>Enhancv report</h4>
                          <p>{enhancvEngine?.reason || "Enhancv is not configured."}</p>
                        </div>
                        <span className="external-badge">External</span>
                      </div>
                      {!enhancvEngine?.available ? (
                        <div className="inline-notice">Add the Enhancv settings to your local .env, then restart Carivyo.</div>
                      ) : !externalReport ? (
                        <div className="enhancv-panel__action">
                          <label className="semantic-consent">
                            <input
                              type="checkbox"
                              checked={externalConsent}
                              onChange={(event) => setExternalConsent(event.target.checked)}
                            />
                            <span>Send this PDF and job description to my authorized Enhancv account.</span>
                          </label>
                          <button className="button button--secondary" type="button" onClick={() => void runEnhancv()} disabled={busy || !externalConsent}>
                            <Gauge aria-hidden="true" /> Run Enhancv
                          </button>
                        </div>
                      ) : externalReport.status === "running" ? (
                        <div className="loading-panel" role="status">
                          <LoaderCircle className="spin" aria-hidden="true" /> Waiting for Enhancv…
                        </div>
                      ) : externalReport.status === "failed" ? (
                        <div className="inline-error" role="alert">
                          {externalReport.error || externalReport.report.blocker || "Enhancv could not produce a report."}
                        </div>
                      ) : (
                        <div className="enhancv-result">
                          <div className="ats-score" aria-label={`Enhancv score ${externalReport.score ?? "unavailable"}`}>
                            <Gauge aria-hidden="true" />
                            <strong>{externalReport.score ?? "—"}</strong>
                            <span>Enhancv</span>
                          </div>
                          <div className="enhancv-result__sections">
                            {Object.entries(externalReport.report.sections || {}).map(([label, value]) => (
                              <div key={label}><span>{label.replaceAll(/([A-Z])/g, " $1")}</span><strong>{value ?? "N/A"}</strong></div>
                            ))}
                          </div>
                          {externalReport.report.report_text ? (
                            <details>
                              <summary>Full Enhancv report</summary>
                              <pre>{externalReport.report.report_text}</pre>
                            </details>
                          ) : null}
                          <small>{externalReport.report.disclaimer}</small>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>

                  </div>
                </details>

                <details className="resume-supporting-details">
                  <summary>Changes and remaining gaps</summary>
                  <div className="resume-supporting-details__body">
                <h4>Meaningful changes</h4>
                <div className="change-list">
                  {run.result.changes.length ? (
                    run.result.changes.slice(0, 6).map((change, index) => (
                      <div key={`${change.after || change.before}-${index}`}>
                        <span className="change-type">{change.type}</span>
                        <p>{change.after || change.before}</p>
                        <small>{change.reason}</small>
                      </div>
                    ))
                  ) : (
                    <div>
                      <span className="change-type">keep</span>
                      <p>Approved base claims remain unchanged.</p>
                      <small>Only relevance and deterministic validation were recomputed.</small>
                    </div>
                  )}
                </div>

                {run.result.custom_instruction_interpretation.length ? (
                  <details className="gap-details">
                    <summary>How your instructions were interpreted</summary>
                    <ul className="instruction-interpretation">
                      {run.result.custom_instruction_interpretation.map((item, index) => (
                        <li key={`${String(item.type)}-${index}`}>
                          <strong>{String(item.type).replaceAll("_", " ")}</strong>
                          <span>{String(item.value)}</span>
                          <small>{String(item.status)}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}

                {run.result.remaining_gaps.length ? (
                  <details className="gap-details">
                    <summary>{run.result.remaining_gaps.length} remaining gaps</summary>
                    <ul className="detail-list detail-list--risk">
                      {run.result.remaining_gaps.map((gap) => <li key={gap}>{gap}</li>)}
                    </ul>
                  </details>
                ) : null}

                  </div>
                </details>

              </section>
            </div>
          </>
        )}

        {notice ? <div className="inline-notice resume-studio__error" role="status">{notice}</div> : null}
        {error ? <div className="inline-error resume-studio__error" role="alert">{error}</div> : null}
      </section>
    </div>
  );
}

function runVariantKey(runId: string, variant: number) {
  return `${runId}:${variant}`;
}

function isBoundToRun(
  value: Pick<BoundPreview | BoundSemanticReview, "runId" | "variant">,
  run: ResumeRun
) {
  return value.runId === run.id && value.variant === run.result.variant;
}

function safeOfficialUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function ATSCheckRow({ check }: { check: ATSCheck }) {
  return (
    <details className={`ats-check ats-check--${check.status}`}>
      <summary>
        {check.status === "fail" ? (
          <AlertTriangle aria-hidden="true" />
        ) : (
          <MinusCircle aria-hidden="true" />
        )}
        <span>{check.label}</span>
        <strong>{check.status === "fail" ? "Fix" : "Review"}</strong>
      </summary>
      {check.evidence.length ? (
        <ul>{check.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : null}
      <p><strong>Suggested action:</strong> {check.suggestion}</p>
    </details>
  );
}

const VALIDATION_CHECKS = [
  { key: "export_ok", label: "Exported document" },
  { key: "page_count_ok", label: "Page limit" },
  { key: "text_extraction_ok", label: "Readable text extraction" },
  { key: "links_ok", label: "Visible links" },
  { key: "identity_ok", label: "Confirmed identity" },
  { key: "section_order_ok", label: "Section reading order" },
  { key: "visual_ok", label: "Machine raster checks" },
  { key: "evidence_ok", label: "Approved evidence only" },
  { key: "change_budget_status", label: "Tailoring change budget" }
] as const;

function validationPassed(key: string, value: unknown) {
  return (
    value === true ||
    (key === "change_budget_status" &&
      ["within_target", "within_review_budget", "not_applicable"].includes(String(value)))
  );
}

function humanizeValidationValue(
  key: string,
  value: unknown
) {
  if (typeof value === "boolean") return value ? "Passed" : "Review";
  if (key === "change_percent" && typeof value === "number") return `${value}%`;
  if (value === null) return "N/A";
  if (value === undefined) return "Unavailable";
  return String(value).replaceAll("_", " ");
}

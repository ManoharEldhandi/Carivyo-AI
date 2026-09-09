import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ATSSemanticReview, ExternalATSReport, Job, ResumeRun } from "../types";
import { ResumeStudio } from "./ResumeStudio";

vi.mock("../api", () => ({
  api: {
    createResume: vi.fn(),
    runtimes: vi.fn(),
    latestResumeRun: vi.fn(),
    reviseResume: vi.fn(),
    approveResume: vi.fn(),
    artifact: vi.fn(),
    atsEngines: vi.fn(),
    enhancvReport: vi.fn(),
    createEnhancvReport: vi.fn(),
    resumeSource: vi.fn(),
    updateResumeSource: vi.fn(),
    createAtsSemanticReview: vi.fn(),
    prepareApplication: vi.fn(),
    openApply: vi.fn()
  }
}));

const job: Job = {
  id: "job-1",
  title: "Backend Software Engineer",
  company: "Acme",
  description: "Build APIs",
  location: "Bengaluru",
  work_mode: "hybrid",
  posted_at: "2026-07-17T00:00:00Z",
  apply_url: "https://jobs.example.com/1",
  source_url: "https://jobs.example.com/1",
  source_family: "greenhouse",
  live_state: "live",
  freshness_class: "verified_24h",
  verified_at: "2026-07-17T00:15:00Z",
  score: 82,
  tier: "strong",
  factors: { role_fit: 23 },
  reasons: [],
  risks: [],
  evidence_ids: []
};

function makeRun(variant: number, status = "awaiting_approval") {
  return {
    id: "run-1",
    job_id: job.id,
    status,
    stage: status === "ready_to_apply" ? "approved" : "review",
    mode: variant === 1 ? "tailor" : "revise",
    interpretation: [],
    result: {
      status,
      source_compiler: "tectonic",
      editable_source_exact: true,
      mode: variant === 1 ? "tailor" : "revise",
      custom_instruction_interpretation: [],
      coverage: { direct: [], transferable: [], unsupported: [], unclear: [] },
      changes: [],
      validation: {
        export_ok: true,
        page_count_ok: true,
        text_extraction_ok: true,
        links_ok: true,
        identity_ok: true,
        section_order_ok: true,
        visual_ok: true,
        evidence_ok: true,
        change_budget_status: "within_target"
      },
      ats_analysis: {
        overall_score: 91,
        parse_rate: 100,
        category_summaries: [],
        checks: [],
        critical_failures: [],
        analyzer_version: "test",
        disclaimer: "Deterministic diagnostic only.",
        protected_trait_policy: "Protected traits are excluded.",
        scoring: { not_applicable_check_ids: [] }
      },
      ats_comparison: {
        baseline_scope: "Imported resume baseline.",
        baseline_score: 80,
        current_score: 91,
        score_delta: 11,
        analyzer_version: "test",
        categories: []
      },
      remaining_gaps: [],
      interview_probes: [],
      artifacts: { render: `render-${variant}.png`, pdf: `resume-${variant}.pdf` },
      variant
    }
  } as unknown as ResumeRun;
}

const semanticReview: ATSSemanticReview = {
  id: "review-1",
  run_id: "run-1",
  status: "complete",
  provider: "codex",
  model: "test-model",
  reasoning_effort: "low",
  response: {
    review_type: "ai_assisted_semantic",
    authoritative: false,
    disclaimer: "AI-assisted and evidence-bound.",
    deterministic_reference: { overall_score: 91, authoritative: true },
    findings: [
      {
        category: "evidence",
        severity: "low",
        claim: "Variant one semantic finding",
        resume_evidence: "API project",
        jd_evidence: "Build APIs",
        recommendation: "Keep the evidence specific.",
        confidence: 0.9,
        ai_assisted: true,
        evidence_verification: {
          status: "verified",
          resume_evidence: true,
          jd_evidence: true
        }
      }
    ]
  },
  usage: {
    input_tokens: 10,
    output_tokens: 5,
    cache_read_tokens: 0,
    kind: "provider"
  }
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function renderCreatedRun(run: ResumeRun) {
  vi.mocked(api.createResume).mockResolvedValue(run);
  render(<ResumeStudio job={job} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /create tailored resume/i }));
  await screen.findByLabelText(`Resume draft ${run.result.variant}`);
}

describe("ResumeStudio run and variant state", () => {
  const createObjectURL = vi.fn(() => "");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    vi.mocked(api.runtimes).mockResolvedValue({
      mode: "provider",
      selection: { provider: "codex", model: "gpt-5.6-terra", reasoning_effort: "low" },
      providers: [
        {
          id: "codex",
          name: "Codex CLI",
          kind: "cli",
          available: true,
          supports_sessions: true,
          supports_usage: false,
          privacy: "provider",
          models: [
            {
              id: "gpt-5.6-terra",
              name: "GPT-5.6 Terra",
              profile: "balanced",
              recommended: true,
              reasoning_efforts: ["low", "medium", "high", "xhigh"]
            }
          ]
        }
      ]
    });
    vi.mocked(api.latestResumeRun).mockResolvedValue({ run: null });
    vi.mocked(api.atsEngines).mockResolvedValue({
      default: "local",
      engines: [
        {
          id: "local",
          label: "Carivyo local ATS",
          available: true,
          external: false,
          configured: true,
          reason: "Ready",
          sends_full_documents: false
        },
        {
          id: "enhancv",
          label: "Enhancv",
          available: false,
          external: true,
          configured: false,
          reason: "Not configured",
          sends_full_documents: true
        }
      ]
    });
    createObjectURL.mockImplementation(
      () => `blob:preview-${createObjectURL.mock.calls.length}`
    );
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURL
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("ignores an old render and gates approval on the current variant image load", async () => {
    const oldRender = deferred<Blob>();
    const revisedRun = deferred<ResumeRun>();
    const currentRender = deferred<Blob>();
    vi.mocked(api.artifact)
      .mockImplementationOnce(() => oldRender.promise)
      .mockImplementationOnce(() => currentRender.promise);
    vi.mocked(api.reviseResume).mockImplementation(() => revisedRun.promise);
    vi.mocked(api.approveResume).mockResolvedValue(makeRun(2, "ready_to_apply"));

    await renderCreatedRun(makeRun(1));
    const approval = screen.getByRole("button", { name: /approve resume/i });
    expect(approval).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/request changes/i), {
      target: { value: "Move the API project higher." }
    });
    fireEvent.click(screen.getByRole("button", { name: /^revise$/i }));
    await waitFor(() => expect(api.reviseResume).toHaveBeenCalledWith("run-1", expect.any(String)));

    await act(async () => oldRender.resolve(new Blob(["old"])));
    expect(screen.queryByRole("img", { name: /rendered resume preview/i })).not.toBeInTheDocument();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");

    await act(async () => revisedRun.resolve(makeRun(2)));
    await screen.findByLabelText("Resume draft 2");
    await waitFor(() => expect(api.artifact).toHaveBeenCalledTimes(2));
    await act(async () => currentRender.resolve(new Blob(["current"])));

    const currentImage = await screen.findByRole("img", {
      name: /rendered resume preview/i
    });
    expect(currentImage).toHaveAttribute("src", "blob:preview-2");
    const currentApproval = screen.getByRole("button", {
      name: /approve resume/i
    });
    expect(currentApproval).toBeDisabled();
    fireEvent.click(currentApproval);
    expect(api.approveResume).not.toHaveBeenCalled();

    fireEvent.load(currentImage);
    expect(currentApproval).toBeEnabled();
    fireEvent.click(currentApproval);
    await waitFor(() => expect(api.approveResume).toHaveBeenCalledWith("run-1"));
  });

  it("clears a semantic review before revising the same run to a new variant", async () => {
    vi.mocked(api.artifact).mockResolvedValue(new Blob(["preview"]));
    vi.mocked(api.createAtsSemanticReview).mockResolvedValue(semanticReview);
    const revisedRun = deferred<ResumeRun>();
    vi.mocked(api.reviseResume).mockImplementation(() => revisedRun.promise);

    await renderCreatedRun(makeRun(1));
    const image = await screen.findByRole("img", { name: /rendered resume preview/i });
    fireEvent.load(image);
    fireEvent.click(screen.getByRole("checkbox", { name: /full extracted resume/i }));
    fireEvent.click(screen.getByRole("button", { name: /check with ai/i }));
    expect(await screen.findByText("Variant one semantic finding")).toBeInTheDocument();
    expect(api.createAtsSemanticReview).toHaveBeenCalledWith("run-1", true);

    fireEvent.change(screen.getByLabelText(/request changes/i), {
      target: { value: "Use a tighter summary." }
    });
    fireEvent.click(screen.getByRole("button", { name: /^revise$/i }));
    expect(screen.queryByText("Variant one semantic finding")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /rendered resume preview/i })).not.toBeInTheDocument();

    await act(async () => revisedRun.resolve(makeRun(2)));
    await screen.findByLabelText("Resume draft 2");
    expect(screen.queryByText("Variant one semantic finding")).not.toBeInTheDocument();
  });

  it("opens TeX in the website and rebuilds from the edited source", async () => {
    const first = makeRun(1);
    const second = makeRun(2);
    vi.mocked(api.artifact).mockResolvedValue(new Blob(["render"]));
    vi.mocked(api.resumeSource).mockResolvedValue({
      run_id: first.id,
      variant: 1,
      language: "latex",
      editable: true,
      filename: "resume1.tex",
      source_hash: "hash",
      source: "\\documentclass{article}\n\\begin{document}\nOriginal resume content that is long enough for the editor test.\\end{document}"
    });
    vi.mocked(api.updateResumeSource).mockResolvedValue(second);

    await renderCreatedRun(first);
    fireEvent.click(screen.getByRole("button", { name: /edit tex/i }));
    const editor = await screen.findByLabelText("TeX code");
    fireEvent.change(editor, {
      target: {
        value: "\\documentclass{article}\n\\begin{document}\nUpdated resume content that is long enough for the editor test.\\end{document}"
      }
    });
    fireEvent.click(screen.getByRole("button", { name: /compile and rebuild/i }));

    await waitFor(() => expect(api.updateResumeSource).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.updateResumeSource).mock.calls[0][0]).toBe(first.id);
    expect(vi.mocked(api.updateResumeSource).mock.calls[0][1]).toContain("Updated resume content");
    await screen.findByLabelText("Resume draft 2");
  });

  it("runs Enhancv only after the user selects it and confirms sharing", async () => {
    const first = makeRun(1);
    const report = {
      id: "external-1",
      run_id: first.id,
      variant: first.result.variant,
      resume_pdf_hash: "pdf-hash-1",
      job_description_hash: "jd-hash-1",
      engine: "enhancv",
      status: "complete",
      score: 88,
      report: {
        ok: true,
        provider: "Enhancv",
        mode: "jd-tailored",
        score: 88,
        sections: { tailoring: "91" },
        disclaimer: "External diagnostic."
      }
    } as ExternalATSReport;
    vi.mocked(api.atsEngines).mockResolvedValue({
      default: "local",
      engines: [
        {
          id: "local",
          label: "Carivyo local ATS",
          available: true,
          external: false,
          configured: true,
          reason: "Ready",
          sends_full_documents: false
        },
        {
          id: "enhancv",
          label: "Enhancv",
          available: true,
          external: true,
          configured: true,
          reason: "Ready through the authorized local account",
          sends_full_documents: true
        }
      ]
    });
    vi.mocked(api.artifact).mockResolvedValue(new Blob(["render"]));
    vi.mocked(api.createEnhancvReport).mockResolvedValue(report);

    await renderCreatedRun(first);
    fireEvent.click(screen.getByRole("radio", { name: "Enhancv" }));
    const runButton = screen.getByRole("button", { name: /run enhancv/i });
    expect(runButton).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /send this pdf/i }));
    fireEvent.click(runButton);

    await screen.findByLabelText("Enhancv score 88");
    expect(api.createEnhancvReport).toHaveBeenCalledWith(first.id, true);
  });
});

describe("ResumeStudio official application handoff", () => {
  beforeEach(() => {
    vi.mocked(api.latestResumeRun).mockResolvedValue({ run: null });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:preview")
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn()
    });
    vi.mocked(api.artifact).mockResolvedValue(new Blob(["preview"]));
    vi.mocked(api.prepareApplication).mockResolvedValue({
      id: "application-1",
      job_id: job.id,
      resume_run_id: "run-1",
      status: "draft",
      notes: "",
      title: job.title,
      company: job.company,
      location: job.location,
      apply_url: job.apply_url,
      allowed_transitions: ["opened", "applied"],
      created_at: "2026-07-17T00:20:00Z",
      updated_at: "2026-07-17T00:20:00Z"
    });
    vi.mocked(api.openApply).mockResolvedValue({
      application: {} as never,
      official_url: job.apply_url,
      warning: "Review and submit it yourself."
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("reports a blocked popup without recording or claiming a successful open", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    await renderCreatedRun(makeRun(1, "ready_to_apply"));

    fireEvent.click(screen.getByRole("button", { name: /open official application/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /browser blocked the official application tab/i
    );
    expect(api.prepareApplication).not.toHaveBeenCalled();
    expect(api.openApply).not.toHaveBeenCalled();
    expect(screen.queryByText(/official application opened in a new tab/i)).not.toBeInTheDocument();
  });

  it("reserves a blank tab synchronously and navigates it only after verification", async () => {
    const replace = vi.fn();
    const applicationWindow = {
      opener: window,
      closed: false,
      close: vi.fn(),
      location: { replace }
    } as unknown as Window;
    const openWindow = vi.spyOn(window, "open").mockReturnValue(applicationWindow);
    await renderCreatedRun(makeRun(1, "ready_to_apply"));

    fireEvent.click(screen.getByRole("button", { name: /open official application/i }));

    expect(openWindow).toHaveBeenCalledWith("about:blank", "_blank");
    expect(openWindow.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.prepareApplication).mock.invocationCallOrder[0]
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith(job.apply_url));
    expect(applicationWindow.opener).toBeNull();
    expect(api.prepareApplication).toHaveBeenCalledWith(job.id, "run-1");
    expect(api.openApply).toHaveBeenCalledWith(job.id);
    expect(await screen.findByRole("status")).toHaveTextContent(
      /official application opened in a new tab/i
    );
  });

  it("restores the latest saved run after reopening Resume Studio", async () => {
    vi.mocked(api.latestResumeRun).mockResolvedValue({
      run: makeRun(2, "ready_to_apply")
    });

    render(<ResumeStudio job={job} onClose={vi.fn()} />);

    expect(await screen.findByLabelText("Resume draft 2")).toBeInTheDocument();
    expect(api.createResume).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /new version/i })).toBeInTheDocument();
  });

  it("uses Terra at extra-high reasoning for a new Codex design review", async () => {
    vi.mocked(api.createResume).mockResolvedValue(makeRun(1));
    render(<ResumeStudio job={job} onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /create tailored resume/i }));

    await waitFor(() => {
      expect(api.createResume).toHaveBeenCalledWith(
        job.id,
        expect.any(String),
        "balanced",
        expect.objectContaining({
          model: "gpt-5.6-terra",
          reasoning_effort: "xhigh",
          check_public_github: false
        })
      );
    });
  });
});

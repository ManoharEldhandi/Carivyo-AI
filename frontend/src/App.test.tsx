import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { App } from "./App";
import { Onboarding } from "./components/Onboarding";
import { ProfilePage } from "./components/ProfilePage";
import type { ProfilePayload, RuntimeState } from "./types";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("Carivyo application shell", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) {
          return jsonResponse({ token: "test-session" });
        }
        if (url.endsWith("/api/runtime/providers")) {
          return jsonResponse({
            providers: [],
            mode: "degraded",
            selection: { provider: "", model: "", reasoning_effort: "low" }
          });
        }
        if (url.endsWith("/api/profile")) {
          return jsonResponse({ onboarding_required: true });
        }
        return jsonResponse({ detail: "Unexpected request" }, 500);
      })
    );
  });

  it("shows the zero-configuration onboarding experience", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        name: /turn your resume into a focused job search/i
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /drop your resume here/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/stored on this device/i)).toBeInTheDocument();
  });

  it("has no detectable structural accessibility violations on first launch", async () => {
    render(<App />);
    await screen.findByRole("heading", {
      name: /turn your resume into a focused job search/i
    });
    const results = await axe.run(document.body, {
      rules: {
        "color-contrast": { enabled: false }
      }
    });
    expect(results.violations).toEqual([]);
  });

  it("uses product navigation and exposes persisted model and priority controls", async () => {
    const profile = {
      id: "profile-1",
      version: "profile-version",
      profile: {
        identity: { name: "Asha", links: [] },
        skills: ["Python", "FastAPI"],
        role_families: ["Backend Engineer"],
        highlights: []
      },
      capsule: "Asha targets evidence-backed backend roles.",
      preferences: [
        {
          id: "pref-1",
          key: "target_roles",
          value: ["Backend Engineer", "Platform Engineer"],
          kind: "hard",
          source: "user",
          confidence: 1
        },
        {
          id: "pref-2",
          key: "preferred_locations",
          value: ["Hyderabad", "Bengaluru"],
          kind: "hard",
          source: "user",
          confidence: 1
        },
        {
          id: "pref-3",
          key: "freshness_hours",
          value: 72,
          kind: "hard",
          source: "user",
          confidence: 1
        }
      ],
      evidence: [],
      resume_bases: [],
      search_plan: null
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return jsonResponse({ token: "test-session" });
        if (url.endsWith("/api/runtime/providers")) {
          return jsonResponse({
            mode: "ai_available",
            selection: {
              provider: "codex",
              model: "gpt-efficient",
              reasoning_effort: "low"
            },
            providers: [
              {
                id: "codex",
                name: "Codex CLI",
                kind: "cli",
                available: true,
                supports_sessions: true,
                supports_usage: true,
                privacy: "provider",
                models: [
                  {
                    id: "gpt-efficient",
                    name: "Efficient",
                    profile: "efficient",
                    recommended: true,
                    detail: "Fast, token-conscious processing.",
                    reasoning_efforts: ["low", "medium"],
                    use_cases: ["profile", "resume_review"]
                  }
                ],
                selected_model: "gpt-efficient",
                selected_reasoning_effort: "low"
              }
            ]
          });
        }
        if (url.endsWith("/api/profile")) return jsonResponse(profile);
        if (url.endsWith("/api/jobs")) {
          return jsonResponse({
            jobs: [],
            count: 0,
            freshness: {},
            locations: {},
            contract: {
              target_roles: ["Backend Engineer", "Platform Engineer"],
              locations: ["Hyderabad", "Bengaluru"],
              work_modes: ["hybrid"],
              freshness_hours: 48,
              location_policy: "strict",
              role_policy: "strict",
              source_policy: "official_direct"
            },
            latest_run: { status: "not_run", coverage: {} }
          });
        }
        return jsonResponse({ detail: "Unexpected request" }, 500);
      })
    );

    render(<App />);
    await screen.findByRole("heading", { name: "Jobs" });
    expect(screen.getAllByText("Codex CLI").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Efficient").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Jobs" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Applications" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Assistant" })).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Profile" })[0]);
    expect(await screen.findByRole("heading", { name: /search priorities/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Target roles priority 1")).toHaveValue("Backend Engineer");
    expect(screen.getByRole("heading", { name: /choose how carivyo uses ai/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /efficient.*recommended default/i })).toBeInTheDocument();
    expect(screen.getByText(/profile, resume review/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /^medium$/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^high$/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Advanced preferences"));
    [
      "Preferred industries",
      "Preferred companies",
      "Excluded companies",
      "Priority skills",
      "Employment types",
      "Minimum salary",
      "Salary currency",
      "Salary period"
    ].forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "Freshness limit" })).toHaveValue("72");
    expect(screen.getByRole("option", { name: /72 hours/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /168 hours/i })).toBeInTheDocument();
    expect(screen.getByText(/upload new resume/i)).toBeInTheDocument();
  });
});

describe("onboarding profile review", () => {
  it("validates extracted values and only completes after backend confirmation", async () => {
    let confirmAttempts = 0;
    const confirmPayloads: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/onboarding/import")) {
          return jsonResponse({
            session_id: "onboarding-session",
            status: "ready",
            summary: {
              name: "Asha Rao",
              email: "asha@example.com",
              phone: "+91 98765 43210",
              links: ["https://github.com/asha"],
              skills: ["Python", "FastAPI"],
              role_tracks: ["Backend Engineer"],
              highlights: ["Built a production API"],
              claim_count: 7
            },
            conflicts: [],
            progress: { answered: 2, total: 2 }
          });
        }
        if (url.endsWith("/api/onboarding/confirm")) {
          confirmAttempts += 1;
          confirmPayloads.push(JSON.parse(String(init?.body)));
          if (confirmAttempts === 1) {
            return jsonResponse({ detail: "Profile confirmation was rejected." }, 500);
          }
          return jsonResponse({
            profile_version: "profile-v1",
            preference_version: "preference-v1",
            search_plan_version: "plan-v1",
            search_run_id: "run-v1"
          });
        }
        return jsonResponse({ detail: "Unexpected request" }, 500);
      })
    );
    const onComplete = vi.fn().mockResolvedValue(undefined);

    render(<Onboarding onComplete={onComplete} />);
    fireEvent.change(screen.getByLabelText("Upload resume file"), {
      target: { files: [new File(["resume"], "resume.txt", { type: "text/plain" })] }
    });

    const reviewSummary = await screen.findByText("Review extracted profile");
    expect(reviewSummary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText(/role suggestions are not confirmed/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Name (required)")).toHaveValue("Asha Rao");
    expect(screen.getByLabelText("Email")).toHaveValue("asha@example.com");
    expect(screen.getByLabelText("Phone")).toHaveValue("+91 98765 43210");
    expect(screen.getByLabelText(/^Links$/)).toHaveValue(
      "https://github.com/asha"
    );
    expect(screen.getByLabelText(/^Suggested roles \(required\)$/)).toHaveValue(
      "Backend Engineer"
    );
    const accessibility = await axe.run(reviewSummary.closest("details") as HTMLElement, {
      rules: { "color-contrast": { enabled: false } }
    });
    expect(accessibility.violations).toEqual([]);

    fireEvent.change(screen.getByLabelText("Name (required)"), {
      target: { value: " " }
    });
    fireEvent.click(screen.getByRole("button", { name: /save profile and find jobs/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/add your name/i);
    expect(confirmAttempts).toBe(0);

    fireEvent.change(screen.getByLabelText("Name (required)"), {
      target: { value: "Asha Rao" }
    });
    fireEvent.change(screen.getByLabelText(/^Suggested roles \(required\)$/), {
      target: { value: "\n, " }
    });
    fireEvent.click(screen.getByRole("button", { name: /save profile and find jobs/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one role direction/i);
    expect(confirmAttempts).toBe(0);

    fireEvent.change(screen.getByLabelText(/^Suggested roles \(required\)$/), {
      target: { value: "Backend Engineer,\nPlatform Engineer" }
    });
    fireEvent.change(screen.getByLabelText(/^Links$/), {
      target: { value: "https://github.com/asha,\nhttps://asha.dev" }
    });
    fireEvent.change(screen.getByLabelText(/^Skills$/), {
      target: { value: "Python,\nFastAPI, React" }
    });
    fireEvent.click(screen.getByRole("button", { name: /save profile and find jobs/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Profile confirmation was rejected."
    );
    expect(onComplete).not.toHaveBeenCalled();
    expect(confirmAttempts).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: /save profile and find jobs/i }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("run-v1"));
    expect(confirmPayloads[1]).toMatchObject({
      session_id: "onboarding-session",
      start_search: true,
      profile_review: {
        name: "Asha Rao",
        links: ["https://github.com/asha", "https://asha.dev"],
        skills: ["Python", "FastAPI", "React"],
        role_tracks: ["Backend Engineer", "Platform Engineer"]
      }
    });
  });
});

describe("candidate profile editor", () => {
  it("validates reviewable values and only confirms a version returned by the backend", async () => {
    const profile: ProfilePayload = {
      id: "profile-1",
      version: "profile-v1",
      profile: {
        identity: {
          name: "Asha Rao",
          email: "asha@example.com",
          phone: "+91 98765 43210",
          location: "Hyderabad",
          links: ["https://github.com/asha"]
        },
        skills: ["Python", "FastAPI"],
        role_families: ["Backend Engineer"],
        highlights: ["Built a production API"]
      },
      capsule: "Evidence-backed backend candidate.",
      preferences: [],
      evidence: [],
      resume_bases: [],
      search_plan: {
        version: "plan-v1",
        status: "ready",
        plan: { target_roles: ["Backend Engineer"] }
      }
    };
    const runtime: RuntimeState = {
      providers: [],
      mode: "degraded",
      selection: { provider: "", model: "", reasoning_effort: "low" }
    };
    let patchAttempts = 0;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        patchAttempts += 1;
        if (patchAttempts === 1) {
          return jsonResponse({ detail: "Profile update was rejected." }, 500);
        }
        const updatedProfile = JSON.parse(String(init.body));
        return jsonResponse({
          ...profile,
          version: "profile-v2",
          profile: updatedProfile,
          search_plan: {
            version: "plan-v2",
            status: "ready",
            plan: { target_roles: ["Backend Engineer"] }
          }
        });
      }
      return jsonResponse(profile);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onProfileRefresh = vi.fn();

    render(
      <ProfilePage
        profile={profile}
        onProfileRefresh={onProfileRefresh}
        runtime={runtime}
        onRuntimeChange={vi.fn()}
      />
    );

    const summary = screen.getByText("Review profile details");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(summary);
    expect(screen.getByText(/edit anything that is wrong/i)).toBeInTheDocument();
    const accessibility = await axe.run(summary.closest("details") as HTMLElement, {
      rules: { "color-contrast": { enabled: false } }
    });
    expect(accessibility.violations).toEqual([]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    onProfileRefresh.mockClear();
    expect(screen.getByLabelText("Target roles priority 1")).toHaveValue("Backend Engineer");

    fireEvent.change(screen.getByLabelText("Candidate name (required)"), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/add the candidate name/i);
    expect(patchAttempts).toBe(0);

    fireEvent.change(screen.getByLabelText("Candidate name (required)"), { target: { value: "Asha Rao" } });
    fireEvent.change(screen.getByLabelText("Role families (required)"), { target: { value: "\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one role family/i);
    expect(patchAttempts).toBe(0);

    fireEvent.change(screen.getByLabelText("Role families (required)"), {
      target: { value: "Backend Engineer,\nPlatform Engineer" }
    });
    fireEvent.change(screen.getByLabelText("Skills"), {
      target: { value: "Python,\nFastAPI, React" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Profile update was rejected.");
    expect(onProfileRefresh).not.toHaveBeenCalled();
    expect(screen.queryByText(/saved as user-confirmed immutable version/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      /candidate profile saved/i
    );
    expect(onProfileRefresh).toHaveBeenCalledWith(
      expect.objectContaining({ version: "profile-v2", search_plan: expect.objectContaining({ version: "plan-v2" }) })
    );
    const patchCalls = fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patchCalls[1][1]?.body))).toMatchObject({
      skills: ["Python", "FastAPI", "React"],
      role_families: ["Backend Engineer", "Platform Engineer"]
    });
  });
});

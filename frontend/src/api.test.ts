import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, initializeSession } from "./api";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("local API session recovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("recovers a direct local page from the runtime launch token", async () => {
    vi.stubEnv("VITE_CARIVYO_BOOTSTRAP_TOKEN", "runtime-launch-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ token: "session" }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();

    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("X-Carivyo-Bootstrap")).toBe("runtime-launch-token");
    expect(window.location.hash).toBe("");
  });

  it("prefers the current launcher token over stale session storage", async () => {
    vi.stubEnv("VITE_CARIVYO_BOOTSTRAP_TOKEN", "current-launch-token");
    window.sessionStorage.setItem("carivyo-bootstrap-token", "stale-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ token: "session" }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();

    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("X-Carivyo-Bootstrap")).toBe("current-launch-token");
  });

  it("removes an invalid stored launch token after rejection", async () => {
    window.sessionStorage.setItem("carivyo-bootstrap-token", "expired-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse({ detail: "Invalid bootstrap token" }, 401))
    );

    await expect(initializeSession()).rejects.toMatchObject({ status: 401 });
    expect(window.sessionStorage.getItem("carivyo-bootstrap-token")).toBeNull();
  });

  it("uses the private launch token when establishing the local session", async () => {
    window.history.replaceState(null, "", "/#bootstrap=private-launch-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ token: "session" }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();

    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("X-Carivyo-Bootstrap")).toBe("private-launch-token");
    expect(window.location.hash).toBe("");
    expect(window.sessionStorage.getItem("carivyo-bootstrap-token")).toBe(
      "private-launch-token"
    );
  });

  it("refreshes a rotated local session once and retries the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "initial-token" }))
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid local session token" }, 401))
      .mockResolvedValueOnce(jsonResponse({ token: "rotated-token" }))
      .mockResolvedValueOnce(
        jsonResponse({
          jobs: [],
          count: 0,
          freshness: {},
          locations: {},
          contract: {
            target_roles: ["Backend Engineer"],
            locations: ["Hyderabad"],
            work_modes: ["hybrid"],
            freshness_hours: 48,
            location_policy: "strict",
            role_policy: "strict",
            source_policy: "official_direct"
          },
          latest_run: { status: "not_run", coverage: {} }
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    const response = await api.jobs();

    expect(response.count).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const retriedHeaders = new Headers(fetchMock.mock.calls[3][1].headers);
    expect(retriedHeaders.get("X-Carivyo-Session")).toBe("rotated-token");
  });

  it("persists an explicit provider, model, and reasoning selection", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "settings-token" }))
      .mockResolvedValueOnce(
        jsonResponse({
          selection: {
            provider: "codex",
            model: "gpt-efficient",
            reasoning_effort: "low"
          },
          providers: []
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    await api.updateRuntimeSettings({
      provider: "codex",
      model: "gpt-efficient",
      reasoning_effort: "low"
    });

    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("PATCH");
    expect(JSON.parse(String(request.body))).toEqual({
      provider: "codex",
      model: "gpt-efficient",
      reasoning_effort: "low"
    });
  });

  it("sends the complete strict preference contract without dropping priority order", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "preferences-token" }))
      .mockResolvedValueOnce(jsonResponse({ version: "v2", changed: [], search_plan: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    await api.updatePreferences({
      target_roles: ["Backend Engineer", "Platform Engineer"],
      preferred_locations: ["Hyderabad", "Bengaluru"],
      preferred_industries: ["Developer tools", "Fintech"],
      preferred_companies: ["Acme", "Example"],
      excluded_companies: ["Legacy Corp"],
      priority_skills: ["Python", "FastAPI"],
      work_modes: ["hybrid", "remote"],
      employment_types: ["full_time", "contract"],
      salary_min: 1800000,
      salary_currency: "INR",
      salary_period: "year",
      seniority_tolerance: "0 to 2 years",
      excluded_keywords: ["senior"],
      excluded_locations: ["Pune"],
      location_policy: "strict",
      freshness_hours: 48
    });

    const request = fetchMock.mock.calls[1][1] as RequestInit;
    const payload = JSON.parse(String(request.body));
    expect(request.method).toBe("PATCH");
    expect(payload.target_roles).toEqual(["Backend Engineer", "Platform Engineer"]);
    expect(payload.preferred_locations).toEqual(["Hyderabad", "Bengaluru"]);
    expect(payload).toMatchObject({
      preferred_industries: ["Developer tools", "Fintech"],
      preferred_companies: ["Acme", "Example"],
      excluded_companies: ["Legacy Corp"],
      priority_skills: ["Python", "FastAPI"],
      employment_types: ["full_time", "contract"],
      salary_min: 1800000,
      salary_currency: "INR",
      salary_period: "year",
      location_policy: "strict",
      freshness_hours: 48
    });
  });

  it("sends the complete candidate profile contract to the profile PATCH endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "profile-token" }))
      .mockResolvedValueOnce(jsonResponse({ version: "profile-v2", search_plan: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    await api.updateProfile({
      identity: {
        name: "Asha Rao",
        email: "asha@example.com",
        phone: "+91 98765 43210",
        location: "Hyderabad",
        links: ["https://example.com", "https://github.com/asha"]
      },
      skills: ["Python", "FastAPI"],
      role_families: ["Backend Engineer", "Platform Engineer"],
      highlights: ["Built a production API"]
    });

    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/profile$/);
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("PATCH");
    expect(JSON.parse(String(request.body))).toEqual({
      identity: {
        name: "Asha Rao",
        email: "asha@example.com",
        phone: "+91 98765 43210",
        location: "Hyderabad",
        links: ["https://example.com", "https://github.com/asha"]
      },
      skills: ["Python", "FastAPI"],
      role_families: ["Backend Engineer", "Platform Engineer"],
      highlights: ["Built a production API"]
    });
  });

  it("sends the user-reviewed onboarding profile in the confirmation payload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "onboarding-token" }))
      .mockResolvedValueOnce(
        jsonResponse({
          profile_version: "profile-v1",
          preference_version: "preference-v1",
          search_plan_version: "plan-v1",
          search_run_id: "run-v1"
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    await api.confirmOnboarding("onboarding-session", {
      name: "Asha Rao",
      email: "asha@example.com",
      phone: "+91 98765 43210",
      links: ["https://github.com/asha", "https://asha.dev"],
      skills: ["Python", "FastAPI"],
      role_tracks: ["Backend Engineer", "Platform Engineer"],
      highlights: ["Built a production API"]
    });

    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/onboarding\/confirm$/);
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(JSON.parse(String(request.body))).toEqual({
      session_id: "onboarding-session",
      start_search: true,
      profile_review: {
        name: "Asha Rao",
        email: "asha@example.com",
        phone: "+91 98765 43210",
        links: ["https://github.com/asha", "https://asha.dev"],
        skills: ["Python", "FastAPI"],
        role_tracks: ["Backend Engineer", "Platform Engineer"],
        highlights: ["Built a production API"]
      }
    });
  });

  it("uses preview and explicit confirmation for replacement resumes", async () => {
    const review = {
      name: "Asha Rao",
      email: "asha@example.com",
      phone: "+91 98765 43210",
      links: ["https://github.com/asha"],
      skills: ["Python", "FastAPI"],
      role_tracks: ["Backend Engineer"],
      highlights: ["Built a production API"]
    };
    const preview = {
      draft_id: "replacement-draft",
      session_id: "replacement-draft",
      status: "needs_confirmation",
      summary: review,
      diff: {
        identity: { added: [], removed: [], changed: [] },
        skills: { added: ["FastAPI"], removed: [], changed: [] },
        role_tracks: { added: [], removed: [], changed: [] },
        highlights: { added: [], removed: [], changed: [] }
      }
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "replacement-token" }))
      .mockResolvedValueOnce(jsonResponse(preview))
      .mockResolvedValueOnce(jsonResponse({ ...preview, status: "confirmed", profile: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await initializeSession();
    const response = await api.previewResumeReplacement(
      new File(["resume"], "resume.txt", { type: "text/plain" })
    );
    await api.confirmResumeReplacement(response.draft_id, review);

    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/profile\/resume\/preview$/);
    const previewRequest = fetchMock.mock.calls[1][1] as RequestInit;
    expect(previewRequest.method).toBe("POST");
    expect(previewRequest.body).toBeInstanceOf(FormData);
    expect(String(fetchMock.mock.calls[2][0])).toMatch(/\/api\/profile\/resume\/confirm$/);
    const confirmRequest = fetchMock.mock.calls[2][1] as RequestInit;
    expect(JSON.parse(String(confirmRequest.body))).toEqual({
      draft_id: "replacement-draft",
      profile_review: review
    });
  });
});

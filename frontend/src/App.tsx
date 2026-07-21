import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, LoaderCircle, RefreshCw } from "lucide-react";
import { api, initializeSession } from "./api";
import { ApplicationsPage } from "./components/ApplicationsPage";
import { ChatDrawer } from "./components/ChatDrawer";
import { JobsPage } from "./components/JobsPage";
import { Onboarding } from "./components/Onboarding";
import { ProfilePage } from "./components/ProfilePage";
import { Shell } from "./components/Shell";
import type {
  Job,
  Page,
  ProfilePayload,
  RuntimeSelection,
  RuntimeSettingsResponse,
  RuntimeState
} from "./types";

const deterministicRuntime: RuntimeState = {
  providers: [],
  mode: "degraded",
  selection: { provider: "", model: "", reasoning_effort: "low" }
};

export function App() {
  const [booting, setBooting] = useState(true);
  const [profile, setProfile] = useState<ProfilePayload | null>(null);
  const [runtime, setRuntime] = useState<RuntimeState>(deterministicRuntime);
  const [page, setPage] = useState<Page>("jobs");
  const [chatOpen, setChatOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | undefined>();
  const [activeSearchRun, setActiveSearchRun] = useState<string | undefined>();
  const [fatalError, setFatalError] = useState("");

  const boot = useCallback(async () => {
    setBooting(true);
    setFatalError("");
    try {
      await initializeSession();
      const [runtimeResponse, profileResponse] = await Promise.all([
        api.runtimes(),
        api.profile()
      ]);
      setRuntime({
        providers: runtimeResponse.providers ?? [],
        mode: runtimeResponse.mode ?? "degraded",
        selection: runtimeResponse.selection ?? deterministicRuntime.selection
      });
      setProfile(
        "onboarding_required" in profileResponse ? null : profileResponse
      );
    } catch (caught) {
      setFatalError(
        caught instanceof Error
          ? caught.message
          : "Carivyo could not connect to its local service."
      );
    } finally {
      setBooting(false);
    }
  }, []);

  useEffect(() => {
    void boot();
  }, [boot]);

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setChatOpen(true);
      }
      if (event.key === "Escape") setChatOpen(false);
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);

  const refreshProfile = useCallback((next: ProfilePayload) => {
    setProfile(next);
  }, []);

  const updateRuntime = useCallback(
    async (selection: RuntimeSelection): Promise<RuntimeSettingsResponse> => {
      const response = await api.updateRuntimeSettings(selection);
      setRuntime({
        providers: response.providers,
        selection: response.selection,
        mode: response.providers.some((provider) => provider.available)
          ? "ai_available"
          : "degraded"
      });
      return response;
    },
    []
  );

  async function onboardingComplete(searchRunId?: string) {
    const nextProfile = await api.profile();
    if ("onboarding_required" in nextProfile) {
      throw new Error("The profile did not finish compiling.");
    }
    setProfile(nextProfile);
    setActiveSearchRun(searchRunId);
    setPage("jobs");
  }

  function changePage(next: Page) {
    if (next === "chat") {
      setChatOpen(true);
      return;
    }
    setPage(next);
  }

  if (booting) {
    return (
      <main id="main-content" className="boot-screen" role="status">
        <div className="brand-mark brand-mark--pulse" aria-hidden="true">
          C
        </div>
        <LoaderCircle className="spin" aria-hidden="true" />
        <h1>Opening your local career workspace</h1>
        <p>Checking the database, runtime, and private session…</p>
      </main>
    );
  }

  if (fatalError) {
    const normalizedError = fatalError.toLowerCase();
    const launchProblem = normalizedError.includes("private launch") || normalizedError.includes("launch session");
    return (
      <main id="main-content" className="boot-screen">
        <AlertTriangle aria-hidden="true" />
        <h1>{launchProblem ? "Restart Carivyo" : "Carivyo’s local service is not ready"}</h1>
        <p>
          {launchProblem
            ? "Run make dev again. Carivyo will open the correct local page automatically."
            : fatalError}
        </p>
        <button className="button button--primary" type="button" onClick={() => void boot()}>
          <RefreshCw aria-hidden="true" /> Try again
        </button>
      </main>
    );
  }

  if (!profile) {
    return <Onboarding onComplete={onboardingComplete} />;
  }

  return (
    <Shell
      page={page}
      onPageChange={changePage}
      onOpenChat={() => setChatOpen(true)}
      runtime={runtime}
    >
      {page === "jobs" ? (
        <JobsPage
          activeRunId={activeSearchRun}
          onRunChange={setActiveSearchRun}
          onSelectJob={setSelectedJob}
          onOpenChat={() => setChatOpen(true)}
          onEditPriorities={() => setPage("profile")}
        />
      ) : null}
      {page === "applications" ? <ApplicationsPage /> : null}
      {page === "profile" ? (
        <ProfilePage
          profile={profile}
          onProfileRefresh={refreshProfile}
          runtime={runtime}
          onRuntimeChange={updateRuntime}
        />
      ) : null}
      <ChatDrawer
        open={chatOpen}
        onClose={() => {
          setChatOpen(false);
        }}
        currentPage={page}
        selectedJob={selectedJob}
        runtime={runtime}
        onOpenAISettings={() => {
          setChatOpen(false);
          setPage("profile");
        }}
        onSearchStarted={(runId) => {
          setActiveSearchRun(runId);
          setPage("jobs");
        }}
      />
    </Shell>
  );
}

import { useEffect, useRef, useState } from "react";
import { getJob, type JobStatus } from "../api";

const POLL_INTERVAL_MS = 1500;

/** Polls GET /api/jobs/{jobId} every 1.5s while the job is running, stops
 * automatically once it reaches "done" or "error". See LEARNING_LOG.md
 * section 6 for why polling is how this is done at all. */
export function useJobPolling(jobId: string | null) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const result = await getJob(jobId);
        if (cancelled) return;
        setJob(result);
        if (result.status !== "running" && intervalRef.current !== null) {
          window.clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch {
        // transient network hiccup -- keep polling, don't surface as a job error
      }
    };

    poll();
    intervalRef.current = window.setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [jobId]);

  return job;
}

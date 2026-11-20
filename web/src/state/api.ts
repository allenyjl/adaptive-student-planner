/* The only file that talks to the backend (backend/app/main.py).

   Requests go to /api/..., which the dev server forwards to the FastAPI server
   (see vite.config.ts). Everything is typed, so a change to the data model that
   the backend would refuse shows up here as a type error first. */
import type { Block, Prefs, Task } from '../domain/types';

// What the server holds: the three kinds of data it stores so far.
export interface ServerData {
  /* Identifies the server's copy of the data. While the server keeps data in memory, this
     changes whenever it restarts, because a restart loses the data. A different id from
     the one seen before means: the server no longer has what was sent earlier. */
  storeId: string;
  tasks: Task[];
  blocks: Block[];
  prefs: Prefs | null; // null until preferences are saved for the first time
}

// Everything one action changed, sent together to POST /sync. The server applies all
// of it or none. "save" holds new and changed items in full; "delete" holds ids.
export interface ChangeSet {
  tasks: { save: Task[]; delete: string[] };
  blocks: { save: Block[]; delete: string[] };
  prefs?: Prefs;
}

/* A request that did not succeed.
   status 0: the server could not be reached (offline, server not running, timed out).
   Any other status is the server's answer, for example 422 when it refuses the data. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
  // True when trying again later could work: the server was unreachable or busy.
  // False when the server understood the request and refused it.
  get retryable() { return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500; }
}

export interface Api {
  loadAll(): Promise<ServerData>; // GET /sync
  sync(changes: ChangeSet): Promise<{ storeId: string }>; // POST /sync
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;
const TIMEOUT_MS = 15000;

// The server's explanation of an error, as one line.
async function reason(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : body;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  } catch { return res.statusText; }
}

export function createApi(base = '/api', fetchFn: Fetch = (input, init) => fetch(input, init)): Api {
  async function request(path: string, init?: RequestInit): Promise<Response> {
    try {
      return await fetchFn(base + path, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
    } catch (e) {
      throw new ApiError(0, 'Could not reach the server: ' + (e instanceof Error ? e.message : String(e)));
    }
  }
  return {
    async loadAll() {
      const res = await request('/sync');
      if (!res.ok) throw new ApiError(res.status, await reason(res));
      return (await res.json()) as ServerData;
    },
    async sync(changes) {
      const res = await request('/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });
      if (!res.ok) throw new ApiError(res.status, await reason(res));
      return (await res.json()) as { storeId: string };
    },
  };
}

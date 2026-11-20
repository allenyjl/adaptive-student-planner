/* Keeps the backend in step with the app's state.

   The app still works on its own state object (state/store.ts) and the scheduling
   engine still runs in the browser. This file watches that state and copies every
   change to the server, and loads what the server has when the app starts.

   How it works: it remembers what the server holds (the "mirror"). After any change it
   compares the state with the mirror and sends only what differs, in one all-or-nothing
   request (POST /sync). Because it always compares with what the server really has, a
   failed save needs no special handling: the next attempt sends whatever is still
   different.

   The mirror can be wrong in one case: the server lost its data (today it keeps data in
   memory, so every restart does this). The server's storeId changes when that happens.
   When a save comes back with a different storeId, or the server refuses a save, this
   file asks the server what it holds now and sends whatever is missing.

   Off unless VITE_SYNC=on (see main.tsx). Only tasks, calendar blocks, and preferences
   are stored on the server so far; the rest of the state stays in this browser. */
import { useSyncExternalStore } from 'react';
import type { Block, Prefs, State, Task } from '../domain/types';
import { ApiError, createApi, type Api, type ChangeSet, type ServerData } from './api';
import { store } from './store';

/* ---------- comparing ---------- */

// The same data always gives the same text, whatever order its fields were set in.
export function canon(value: unknown): string {
  const sorted = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sorted);
    if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>;
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(o).sort()) if (o[k] !== undefined) out[k] = sorted(o[k]);
      return out;
    }
    return v;
  };
  return JSON.stringify(sorted(value));
}

// What the server holds, as text per item so it is quick to compare.
export interface Mirror {
  tasks: Map<string, string>; // id -> the task as text
  blocks: Map<string, string>; // id -> the block as text
  prefs: string | null;
}

type Synced = Pick<State, 'tasks' | 'blocks'> & { prefs: Prefs | null };

export const mirrorOf = (d: Synced): Mirror => ({
  tasks: new Map(d.tasks.map((t) => [t.id, canon(t)])),
  blocks: new Map(d.blocks.map((b) => [b.id, canon(b)])),
  prefs: d.prefs ? canon(d.prefs) : null,
});

// What has to be sent so the server matches `state`, or null when it already does.
export function diff(mirror: Mirror, state: Synced): ChangeSet | null {
  const now = mirrorOf(state);
  // Copies, because the app changes its objects in place while a request is on its way.
  const changed = <T extends { id: string }>(items: T[], before: Map<string, string>, after: Map<string, string>) =>
    items.filter((x) => before.get(x.id) !== after.get(x.id)).map((x) => structuredClone(x));
  const gone = (before: Map<string, string>, after: Map<string, string>) => [...before.keys()].filter((id) => !after.has(id));
  const changes: ChangeSet = {
    tasks: { save: changed<Task>(state.tasks, mirror.tasks, now.tasks), delete: gone(mirror.tasks, now.tasks) },
    blocks: { save: changed<Block>(state.blocks, mirror.blocks, now.blocks), delete: gone(mirror.blocks, now.blocks) },
  };
  if (state.prefs && now.prefs !== mirror.prefs) changes.prefs = structuredClone(state.prefs);
  const empty = !changes.tasks.save.length && !changes.tasks.delete.length && !changes.blocks.save.length && !changes.blocks.delete.length && !changes.prefs;
  return empty ? null : changes;
}

/* ---------- syncing ---------- */

/* off:      not connected to a server (the default).
   loading:  fetching what the server has, at start-up.
   saving:   a save is on its way.
   saved:    the server has everything.
   error:    the last attempt failed. `problem` says why. Changes are kept in this
             browser, and the next attempt sends them. */
export type SyncStatus = 'off' | 'loading' | 'saving' | 'saved' | 'error';
export type SyncProblem = 'unreachable' | 'refused' | null;
export interface SyncView { status: SyncStatus; problem: SyncProblem; detail: string }

// The parts of the store the syncer needs. Passed in so tests can use a plain object.
export interface SyncHost {
  get(): State;
  apply(fn: (s: State) => void): void; // change the state and re-render
  subscribe(fn: () => void): () => void; // called after every change
}

export interface SyncOptions {
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
  retryAfterMs?: number[]; // wait this long before each automatic retry; the last one repeats
}

// Set while this browser has changes the server has not confirmed, so a reload knows
// that this browser's copy is the newer one.
const UNSAVED_KEY = 'inflow-web-unsaved';

export function createSync(api: Api, host: SyncHost, opts: SyncOptions = {}) {
  const storage = opts.storage;
  const retryAfterMs = opts.retryAfterMs || [3000, 10000, 30000];
  let view: SyncView = { status: 'off', problem: null, detail: '' };
  const listeners = new Set<() => void>();
  let mirror: Mirror | null = null; // null until the first load succeeds
  let storeId = ''; // which copy of the data the mirror describes
  let inFlight = false; // a save is on its way
  let relearning = false; // asking the server again what it holds
  let relearnedAfterRefusal = false; // so a refused save is looked into once, not forever
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribe: (() => void) | undefined;
  let stopped = false;

  const setView = (status: SyncStatus, problem: SyncProblem = null, detail = '') => {
    if (view.status === status && view.problem === problem && view.detail === detail) return;
    view = { status, problem, detail };
    listeners.forEach((f) => f());
  };
  const flag = (unsaved: boolean) => {
    try { if (unsaved) storage?.setItem(UNSAVED_KEY, '1'); else storage?.removeItem(UNSAVED_KEY); } catch { /* storage unavailable */ }
  };
  const hadUnsaved = () => { try { return storage?.getItem(UNSAVED_KEY) === '1'; } catch { return false; } };

  // Report a failure, and try again later if trying again could help.
  const failed = (e: unknown, again: () => void) => {
    const retryable = !(e instanceof ApiError) || e.retryable;
    setView('error', retryable ? 'unreachable' : 'refused', e instanceof Error ? e.message : String(e));
    if (!retryable || stopped) return; // the server refused the data: the same request would be refused again
    const wait = retryAfterMs[Math.min(failures, retryAfterMs.length - 1)];
    failures++;
    clearTimeout(timer);
    timer = setTimeout(again, wait);
  };

  // Send whatever differs from what the server has. Runs after every change.
  function push() {
    if (stopped || !mirror) return;
    if (inFlight || relearning) return; // whichever is under way is followed by another look
    const state = host.get();
    const changes = diff(mirror, state);
    if (!changes) { flag(false); setView('saved'); return; }
    const sent = mirrorOf(state); // what the server will hold if this succeeds
    clearTimeout(timer);
    flag(true);
    setView('saving');
    inFlight = true;
    api.sync(changes).then(
      (result) => {
        inFlight = false;
        failures = 0;
        // Saved, but to a different copy of the data than the mirror describes: the
        // server lost its data at some point. Find out what it holds and send the rest.
        if (result.storeId !== storeId) { void relearn(); return; }
        mirror = sent;
        relearnedAfterRefusal = false;
        push(); // look again: more may have changed meanwhile
      },
      (e: unknown) => {
        inFlight = false;
        // Refused. That can mean the mirror is wrong (a session whose task the server
        // lost, for one), so check what the server holds and try once more.
        if (e instanceof ApiError && !e.retryable && !relearnedAfterRefusal) { relearnedAfterRefusal = true; void relearn(); return; }
        failed(e, push);
      },
    );
  }

  // Ask the server what it holds now and send whatever it is missing. This browser's
  // copy is kept: mid-session it is the one the student is looking at.
  async function relearn(): Promise<void> {
    if (stopped) return;
    relearning = true;
    try {
      const data = await api.loadAll();
      storeId = data.storeId;
      mirror = mirrorOf(data);
    } catch (e) {
      relearning = false;
      failed(e, () => void relearn());
      return;
    }
    relearning = false;
    push();
  }

  // Fetch what the server has, settle which copy wins, then start watching for changes.
  async function start(): Promise<void> {
    if (stopped) return;
    clearTimeout(timer);
    setView('loading');
    let data: ServerData;
    try { data = await api.loadAll(); } catch (e) { failed(e, () => void start()); return; }
    if (stopped) return;
    failures = 0;
    storeId = data.storeId;
    mirror = mirrorOf(data);
    const serverEmpty = !data.tasks.length && !data.blocks.length && !data.prefs;
    /* Which copy wins:
       - The server is empty (first use, or it restarted and lost its memory): this
         browser's copy is uploaded.
       - This browser has changes that were never confirmed: its copy is the newer one,
         and is uploaded over the server's.
       - Otherwise the server's copy replaces this browser's. */
    if (!serverEmpty && !hadUnsaved()) {
      host.apply((s) => {
        s.tasks = data.tasks;
        s.blocks = data.blocks;
        if (data.prefs) s.prefs = data.prefs;
        // Feedback requests for sessions that no longer exist are dropped.
        s.pending = s.pending.filter((p) => s.blocks.some((b) => b.id === p.blockId));
      });
    }
    unsubscribe ??= host.subscribe(push);
    push();
  }

  return {
    start,
    // Try again now, without waiting for the automatic retry.
    retry() { failures = 0; relearnedAfterRefusal = false; if (mirror) push(); else void start(); },
    stop() { stopped = true; clearTimeout(timer); unsubscribe?.(); },
    view: () => view,
    subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  };
}

/* ---------- the app's own syncer ---------- */

type Syncer = ReturnType<typeof createSync>;
let active: Syncer | null = null;
const OFF: SyncView = { status: 'off', problem: null, detail: '' };
const viewSubs = new Set<() => void>();

// Connect the app's store to the backend. Called once from main.tsx when VITE_SYNC=on.
export function startSync(api: Api = createApi()): Promise<void> {
  active?.stop();
  let storage: Storage | undefined;
  try { storage = localStorage; } catch { /* storage unavailable */ }
  const syncer = createSync(api, { get: () => store.state, apply: (fn) => { store.commit(fn); }, subscribe: (fn) => store.subscribe(fn) }, { storage });
  active = syncer;
  syncer.subscribe(() => viewSubs.forEach((f) => f()));
  window.addEventListener('online', () => { if (active === syncer && syncer.view().status === 'error') syncer.retry(); });
  return syncer.start();
}

export const retrySync = () => active?.retry();

// The current sync status; the calling component re-renders when it changes.
export function useSyncView(): SyncView {
  return useSyncExternalStore((f) => { viewSubs.add(f); return () => { viewSubs.delete(f); }; }, () => (active ? active.view() : OFF));
}

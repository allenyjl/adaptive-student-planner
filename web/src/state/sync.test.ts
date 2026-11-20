/* Tests for saving to the backend, using a pretend server that follows the real one's
   rules (save replaces by id, deleting a task deletes its blocks). No network is used. */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { Block, State, Task } from '../domain/types';
import { NOW, emptyState, mkBlock, mkTask } from '../test/helpers';
import { ApiError, type Api, type ChangeSet, type ServerData } from './api';
import { canon, createSync, diff, mirrorOf, type SyncHost } from './sync';

/* ---------- helpers ---------- */

const HOUR = 3600000;

// A state with two tasks, one session each, and one plain event.
function sampleState(): State {
  const s = emptyState();
  const a = mkTask(s, { title: 'Essay' });
  const b = mkTask(s, { title: 'Problem set' });
  mkBlock(s, { kind: 'session', anchored: false, taskId: a.id, title: a.title, start: NOW + HOUR, end: NOW + 2 * HOUR, eventType: undefined });
  mkBlock(s, { kind: 'session', anchored: false, taskId: b.id, title: b.title, start: NOW + 3 * HOUR, end: NOW + 4 * HOUR, eventType: undefined });
  mkBlock(s, { title: 'Dinner', start: NOW + 10 * HOUR, end: NOW + 11 * HOUR });
  return s;
}

// A pretend server. `fail` makes the next saves fail with the given errors; `failLoad`
// does the same for reading what the server holds.
function fakeServer(initial: Partial<ServerData> = {}) {
  const data: ServerData = { storeId: 'store-1', tasks: [], blocks: [], prefs: null, ...structuredClone(initial) };
  const requests: ChangeSet[] = [];
  const failures: Error[] = [];
  const loadFailures: Error[] = [];
  let hold: (() => void) | null = null; // set to keep a request waiting
  const waiting: (() => void)[] = [];
  const api: Api = {
    async loadAll() {
      if (loadFailures.length) throw loadFailures.shift();
      return structuredClone(data);
    },
    async sync(changes) {
      requests.push(structuredClone(changes));
      if (hold) await new Promise<void>((r) => waiting.push(r));
      if (failures.length) throw failures.shift();
      const put = <T extends { id: string }>(list: T[], item: T) => { const i = list.findIndex((x) => x.id === item.id); if (i >= 0) list[i] = item; else list.push(item); };
      data.blocks = data.blocks.filter((b) => !changes.blocks.delete.includes(b.id) && !(b.taskId && changes.tasks.delete.includes(b.taskId)));
      data.tasks = data.tasks.filter((t) => !changes.tasks.delete.includes(t.id));
      changes.tasks.save.forEach((t) => put<Task>(data.tasks, t));
      changes.blocks.save.forEach((b) => put<Block>(data.blocks, b));
      if (changes.prefs) data.prefs = changes.prefs;
      return { storeId: data.storeId };
    },
  };
  return {
    api, data, requests,
    // What a restart does while data is kept in memory: everything is lost, and the id changes.
    restart: () => { data.tasks = []; data.blocks = []; data.prefs = null; data.storeId += '+'; },
    // The real server refuses a session whose task it does not have.
    refuseOrphans: () => {
      const real = api.sync;
      api.sync = async (changes) => {
        const known = new Set([...data.tasks.map((t) => t.id), ...changes.tasks.save.map((t) => t.id)]);
        if (changes.blocks.save.some((b) => b.taskId && !known.has(b.taskId))) { requests.push(structuredClone(changes)); throw new ApiError(422, 'No task with that id would exist after these changes.'); }
        return real(changes);
      };
    },
    fail: (...errors: Error[]) => { failures.push(...errors); },
    failLoad: (...errors: Error[]) => { loadFailures.push(...errors); },
    pause: () => { hold = () => {}; },
    resume: () => { hold = null; waiting.splice(0).forEach((r) => r()); },
  };
}

// A stand-in for the app's store.
function fakeHost(state: State): SyncHost & { change(fn: (s: State) => void): void } {
  const subs = new Set<() => void>();
  const apply = (fn: (s: State) => void) => { fn(state); subs.forEach((f) => f()); };
  return { get: () => state, apply, change: apply, subscribe: (f) => { subs.add(f); return () => { subs.delete(f); }; } };
}

function fakeStorage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  return { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => { items.set(k, v); }, removeItem: (k: string) => { items.delete(k); }, items };
}

// Let requests that are on their way finish.
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const same = (server: ServerData, s: State) => {
  expect(server.tasks).toEqual(s.tasks);
  expect(server.blocks).toEqual(s.blocks);
  expect(server.prefs).toEqual(s.prefs);
};
const unreachable = () => new ApiError(0, 'Could not reach the server');
const refused = () => new ApiError(422, 'needMin must be at least 0');

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

/* ---------- comparing ---------- */

const NOTHING = mirrorOf({ tasks: [], blocks: [], prefs: null });

describe('diff: what has to be sent', () => {
  test('nothing, when the server already matches', () => {
    const s = sampleState();
    expect(diff(mirrorOf(s), s)).toBeNull();
  });

  test('everything, when the server is empty', () => {
    const s = sampleState();
    const d = diff(NOTHING, s)!;
    expect(d.tasks.save).toEqual(s.tasks);
    expect(d.blocks.save).toEqual(s.blocks);
    expect(d.prefs).toEqual(s.prefs);
    expect(d.tasks.delete).toEqual([]);
    expect(d.blocks.delete).toEqual([]);
  });

  test('only the items that changed, were added, or were removed', () => {
    const s = sampleState();
    const before = mirrorOf(s);
    s.tasks[0].title = 'Essay, second draft';
    const removed = s.blocks.pop()!;
    const added = mkBlock(s, { title: 'Gym', start: NOW + 20 * HOUR, end: NOW + 21 * HOUR });
    const d = diff(before, s)!;
    expect(d.tasks.save).toEqual([s.tasks[0]]);
    expect(d.tasks.delete).toEqual([]);
    expect(d.blocks.save).toEqual([added]);
    expect(d.blocks.delete).toEqual([removed.id]);
    expect(d.prefs).toBeUndefined();
  });

  test('preferences, only when they changed', () => {
    const s = sampleState();
    const before = mirrorOf(s);
    s.prefs.energy = 'evening';
    expect(diff(before, s)).toEqual({ tasks: { save: [], delete: [] }, blocks: { save: [], delete: [] }, prefs: s.prefs });
  });

  test('copies, so later changes in the app do not alter a request already made', () => {
    const s = sampleState();
    const d = diff(NOTHING, s)!;
    s.tasks[0].title = 'Changed afterwards';
    expect(d.tasks.save[0].title).toBe('Essay');
  });

  test('the order fields were set in does not count as a change', () => {
    expect(canon({ a: 1, b: { c: 2, d: 3 } })).toBe(canon({ b: { d: 3, c: 2 }, a: 1 }));
    expect(canon({ a: 1, b: undefined })).toBe(canon({ a: 1 }));
    expect(canon([1, 2])).not.toBe(canon([2, 1])); // the order of a list does count
  });
});

/* ---------- starting up ---------- */

describe('starting up', () => {
  test('an empty server receives this browser\'s copy', async () => {
    const s = sampleState();
    const server = fakeServer();
    const sync = createSync(server.api, fakeHost(s));
    await sync.start();
    await settle();
    expect(sync.view().status).toBe('saved');
    expect(server.requests).toHaveLength(1);
    same(server.data, s);
  });

  test('a server with data replaces this browser\'s copy, and nothing is sent back', async () => {
    const onServer = sampleState();
    const server = fakeServer({ tasks: onServer.tasks, blocks: onServer.blocks, prefs: { ...onServer.prefs, energy: 'evening' } });
    const local = emptyState();
    mkTask(local, { title: 'Only in this browser' });
    const sync = createSync(server.api, fakeHost(local));
    await sync.start();
    await settle();
    expect(local.tasks).toEqual(onServer.tasks);
    expect(local.blocks).toEqual(onServer.blocks);
    expect(local.prefs.energy).toBe('evening');
    expect(server.requests).toHaveLength(0);
    expect(sync.view().status).toBe('saved');
  });

  test('feedback requests for sessions the server does not have are dropped', async () => {
    const onServer = sampleState();
    const server = fakeServer({ tasks: onServer.tasks, blocks: onServer.blocks, prefs: onServer.prefs });
    const local = emptyState();
    local.pending = [{ blockId: onServer.blocks[0].id, endedAt: NOW }, { blockId: 'gone', endedAt: NOW }];
    await createSync(server.api, fakeHost(local)).start();
    expect(local.pending).toEqual([{ blockId: onServer.blocks[0].id, endedAt: NOW }]);
  });

  test('unconfirmed changes from last time win over the server\'s copy', async () => {
    const onServer = sampleState();
    const server = fakeServer({ tasks: onServer.tasks, blocks: onServer.blocks, prefs: onServer.prefs });
    const local = structuredClone(onServer);
    local.tasks[0].title = 'Edited while the server was down';
    local.blocks.pop();
    const storage = fakeStorage({ 'inflow-web-unsaved': '1' });
    const sync = createSync(server.api, fakeHost(local), { storage });
    await sync.start();
    await settle();
    expect(local.tasks[0].title).toBe('Edited while the server was down');
    same(server.data, local);
    expect(storage.items.has('inflow-web-unsaved')).toBe(false); // confirmed now
  });

  test('if the server cannot be reached, the browser\'s copy is kept and loading is retried', async () => {
    const s = sampleState();
    const before = structuredClone(s);
    const server = fakeServer();
    server.failLoad(unreachable());
    const sync = createSync(server.api, fakeHost(s), { retryAfterMs: [1000] });
    await sync.start();
    expect(sync.view()).toMatchObject({ status: 'error', problem: 'unreachable' });
    expect(s).toEqual(before);
    await vi.advanceTimersByTimeAsync(1000);
    await settle();
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
  });
});

/* ---------- saving changes ---------- */

describe('saving changes', () => {
  async function started(opts: Parameters<typeof createSync>[2] = {}) {
    const s = sampleState();
    const server = fakeServer();
    const host = fakeHost(s);
    const sync = createSync(server.api, host, opts);
    await sync.start();
    await settle();
    server.requests.length = 0; // forget the first upload
    return { s, server, host, sync };
  }

  test('one action that changes several things is sent as one request', async () => {
    const { s, server, host, sync } = await started();
    host.change((st) => {
      const t = mkTask(st, { title: 'Lab report' });
      mkBlock(st, { kind: 'session', anchored: false, taskId: t.id, title: t.title, start: NOW + 30 * HOUR, end: NOW + 31 * HOUR, eventType: undefined });
      st.blocks[0].start += HOUR;
      st.blocks[0].end += HOUR;
    });
    expect(sync.view().status).toBe('saving');
    await settle();
    expect(server.requests).toHaveLength(1);
    expect(server.requests[0].tasks.save.map((t) => t.title)).toEqual(['Lab report']);
    expect(server.requests[0].blocks.save).toHaveLength(2); // the new session and the moved one
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
  });

  test('deleting a task and its sessions reaches the server', async () => {
    const { s, server, host } = await started();
    const gone = s.tasks[0].id;
    host.change((st) => { st.tasks = st.tasks.filter((t) => t.id !== gone); st.blocks = st.blocks.filter((b) => b.taskId !== gone); });
    await settle();
    expect(server.requests[0].tasks.delete).toEqual([gone]);
    same(server.data, s);
  });

  test('a change that alters nothing the server stores sends nothing', async () => {
    const { server, host, sync } = await started();
    host.change((st) => { st.now += HOUR; st.onboarded = true; });
    await settle();
    expect(server.requests).toHaveLength(0);
    expect(sync.view().status).toBe('saved');
  });

  test('changes made while a save is on its way are sent right after it', async () => {
    const { s, server, host } = await started();
    server.pause();
    host.change((st) => { st.tasks[0].title = 'First change'; });
    host.change((st) => { st.tasks[1].title = 'Second change'; });
    host.change((st) => { st.prefs.energy = 'evening'; });
    await settle();
    expect(server.requests).toHaveLength(1); // only one request at a time
    server.resume();
    await settle();
    expect(server.requests).toHaveLength(2);
    expect(server.requests[1].tasks.save.map((t) => t.title)).toEqual(['Second change']);
    expect(server.requests[1].prefs?.energy).toBe('evening');
    same(server.data, s);
  });

  test('a save that cannot reach the server is kept and retried on its own', async () => {
    const storage = fakeStorage();
    const { s, server, host, sync } = await started({ storage, retryAfterMs: [1000, 5000] });
    server.fail(unreachable(), unreachable());
    host.change((st) => { st.tasks[0].title = 'Offline edit'; });
    await settle();
    expect(sync.view()).toMatchObject({ status: 'error', problem: 'unreachable' });
    expect(s.tasks[0].title).toBe('Offline edit'); // still on screen
    expect(storage.items.get('inflow-web-unsaved')).toBe('1'); // remembered across a reload

    await vi.advanceTimersByTimeAsync(1000); // first retry fails too
    await settle();
    expect(sync.view().status).toBe('error');
    await vi.advanceTimersByTimeAsync(4999);
    expect(sync.view().status).toBe('error'); // the second wait is longer
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
    expect(storage.items.has('inflow-web-unsaved')).toBe(false);
  });

  test('more changes after a failure are all sent by the next attempt', async () => {
    const { s, server, host, sync } = await started({ retryAfterMs: [60000] });
    server.fail(unreachable());
    host.change((st) => { st.tasks[0].title = 'Edit one'; });
    await settle();
    host.change((st) => { st.tasks[1].title = 'Edit two'; }); // a new change tries again at once
    await settle();
    expect(sync.view().status).toBe('saved');
    expect(server.requests[1].tasks.save.map((t) => t.title)).toEqual(['Edit one', 'Edit two']);
    same(server.data, s);
  });

  test('"Try again" sends at once, without waiting', async () => {
    const { s, server, host, sync } = await started({ retryAfterMs: [60000] });
    server.fail(unreachable());
    host.change((st) => { st.tasks[0].title = 'Offline edit'; });
    await settle();
    sync.retry();
    await settle();
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
  });

  test('a change the server refuses is reported and not retried on a timer', async () => {
    const { s, server, host, sync } = await started({ retryAfterMs: [1000] });
    server.fail(refused(), refused());
    host.change((st) => { st.tasks[0].title = 'Refused edit'; });
    await settle();
    expect(sync.view()).toMatchObject({ status: 'error', problem: 'refused', detail: 'needMin must be at least 0' });
    await vi.advanceTimersByTimeAsync(60000);
    expect(server.requests).toHaveLength(2); // one more try after checking what the server holds, then no more
    expect(s.tasks[0].title).toBe('Refused edit'); // kept in this browser
  });

  test('after stop(), nothing more is sent', async () => {
    const { server, host, sync } = await started();
    sync.stop();
    host.change((st) => { st.tasks[0].title = 'After stopping'; });
    await settle();
    expect(server.requests).toHaveLength(0);
  });
});

/* ---------- when the server loses its data ---------- */

describe('when the server loses its data (a restart, while data is kept in memory)', () => {
  async function started() {
    const s = sampleState();
    const server = fakeServer();
    const host = fakeHost(s);
    const sync = createSync(server.api, host);
    await sync.start();
    await settle();
    server.requests.length = 0;
    return { s, server, host, sync };
  }

  test('the next save notices, and everything is sent again', async () => {
    const { s, server, host, sync } = await started();
    server.restart();
    host.change((st) => { st.tasks[0].title = 'A small edit'; });
    await settle();
    expect(server.requests).toHaveLength(2); // the small edit, then everything that was missing
    expect(sync.view().status).toBe('saved');
    same(server.data, s); // the server has the whole plan again, not just the edit
  });

  test('a save the emptied server refuses is put right without the student doing anything', async () => {
    const { s, server, host, sync } = await started();
    server.refuseOrphans();
    server.restart();
    // Moving a session: the server no longer has the session's task, so it refuses.
    host.change((st) => { st.blocks[0].start += HOUR; st.blocks[0].end += HOUR; });
    await settle();
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
  });

  test('a save that is still refused after checking is reported, and checked only once', async () => {
    const { server, host, sync } = await started();
    server.fail(refused(), refused(), refused());
    host.change((st) => { st.tasks[0].title = 'Refused edit'; });
    await settle();
    expect(sync.view()).toMatchObject({ status: 'error', problem: 'refused' });
    expect(server.requests).toHaveLength(2); // the save, and one more try after checking
    host.change((st) => { st.tasks[1].title = 'Another edit'; });
    await settle();
    expect(server.requests).toHaveLength(3); // a new change tries once, without checking again
  });
});

describe('when checking what the server holds fails', () => {
  test('it is retried, and the save still goes through', async () => {
    const s = sampleState();
    const server = fakeServer();
    const host = fakeHost(s);
    const sync = createSync(server.api, host, { retryAfterMs: [1000] });
    await sync.start();
    await settle();
    server.restart();
    server.failLoad(unreachable());
    host.change((st) => { st.tasks[0].title = 'A small edit'; });
    await settle();
    expect(sync.view()).toMatchObject({ status: 'error', problem: 'unreachable' });
    await vi.advanceTimersByTimeAsync(1000);
    await settle();
    expect(sync.view().status).toBe('saved');
    same(server.data, s);
  });
});

/* The status line: hidden by default, and what the student sees when a save fails. */
import { afterEach, expect, test } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { emptyState, mkTask, renderApp } from '../test/helpers';
import { ApiError, type Api, type ChangeSet } from '../state/api';
import { startSync } from '../state/sync';
import { store } from '../state/store';
import { SyncStatus } from './SyncStatus';

const settle = () => act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); });
let stop: (() => void) | undefined;
afterEach(() => { stop?.(); stop = undefined; });

// Connect the app's real store to a pretend server whose saves can be made to fail.
async function connected() {
  const requests: ChangeSet[] = [];
  const state = { failing: false };
  const api: Api = {
    loadAll: async () => ({ storeId: 'store-1', tasks: [], blocks: [], prefs: null }),
    sync: async (c) => { requests.push(c); if (state.failing) throw new ApiError(0, 'Could not reach the server'); return { storeId: 'store-1' }; },
  };
  await act(async () => { await startSync(api); });
  await settle();
  // Connecting to a server that is never used again ends this one.
  stop = () => { void startSync({ loadAll: () => new Promise(() => {}), sync: async () => ({ storeId: '' }) }); };
  return { requests, state };
}

test('nothing is shown while the app is not connected to a server', () => {
  // No test before this one has connected, so this is the app's default.
  store.replace(emptyState());
  const { container } = render(<SyncStatus />);
  expect(container.textContent).toBe('');
});

test('the app shows that changes are saved, and what to do when they are not', async () => {
  renderApp(emptyState());
  const server = await connected();
  expect(screen.getByText('All changes saved')).toBeTruthy();

  server.state.failing = true;
  act(() => { store.commit((s) => { mkTask(s, { title: 'Essay' }); }); });
  await settle();
  expect(screen.getByText(/Not saved: can’t reach the server/)).toBeTruthy();
  expect(screen.getByText(/kept on this device/)).toBeTruthy();

  server.state.failing = false;
  await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
  await settle();
  expect(screen.getByText('All changes saved')).toBeTruthy();
  expect(server.requests.at(-1)!.tasks.save.map((t) => t.title)).toEqual(['Essay']);
});

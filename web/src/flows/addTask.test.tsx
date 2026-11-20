/* The Add task dialog when a required field is missing: it stays open, says what is
   missing, and brings that message into view (the form scrolls, and the message is at
   the bottom of it). */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { dialog, emptyState, renderApp } from '../test/helpers';
import { store } from '../state/store';

let scrolled: Element[] = [];
beforeEach(() => {
  scrolled = [];
  // The test browser has no scrolling; record what would have been scrolled to.
  Element.prototype.scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
});
afterEach(() => { delete (Element.prototype as Partial<Element>).scrollIntoView; });

test('a missing field keeps the dialog open and brings the message into view each time', async () => {
  const { user } = renderApp(emptyState(), 'tasks');
  await user.click(screen.getAllByRole('button', { name: /add task/i })[0]);
  const d = within(await dialog(/add a task/i));
  const add = () => user.click(d.getByRole('button', { name: 'Add task' }));

  await user.type(d.getByLabelText('Task name'), 'My essay');
  expect(scrolled).toHaveLength(0); // nothing is scrolled before an attempt

  await add();
  const message = d.getByRole('alert');
  expect(message.textContent).toBe('Enter the course.');
  expect(scrolled).toEqual([message]);

  await add(); // the same message again: still brought into view
  expect(scrolled).toEqual([message, message]);

  await user.type(d.getByLabelText(/^course/i), 'ENGL 101');
  expect(message.textContent).toBe(''); // editing clears the message
  await add();
  expect(message.textContent).toBe('Enter how long it will take, or add instructions to get milestones.');
  expect(scrolled).toHaveLength(3);
  expect(store.state.tasks).toHaveLength(0); // nothing was added along the way

  await user.type(d.getByLabelText(/hours/i), '2');
  await add();
  await vi.waitFor(() => expect(screen.queryByRole('dialog', { name: /add a task/i })).toBeNull());
  expect(store.state.tasks.map((t) => t.title)).toEqual(['My essay']);
  expect(scrolled).toHaveLength(3); // a successful attempt scrolls nothing
});

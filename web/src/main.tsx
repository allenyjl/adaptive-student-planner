import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { store } from './state/store';
import { startSync } from './state/sync';
import { App } from './App';

store.init();
// Saving to the backend is off unless VITE_SYNC=on (see web/README.md). Without it the
// app keeps everything in this browser, as before.
if (import.meta.env.VITE_SYNC === 'on') void startSync();
createRoot(document.getElementById('app')!).render(<StrictMode><App /></StrictMode>);

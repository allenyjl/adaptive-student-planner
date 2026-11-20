/* Shows whether the student's changes have reached the server. Renders nothing while
   the app is not connected to one (the default; see state/sync.ts). */
import { retrySync, useSyncView } from '../state/sync';

export function SyncStatus() {
  const v = useSyncView();
  if (v.status === 'off') return null;
  if (v.status === 'error') {
    return (
      <div className="sync sync-error" role="status" title={v.detail}>
        <span>
          {v.problem === 'refused'
            ? 'Not saved: the server refused a change. Your changes are kept on this device.'
            : 'Not saved: can’t reach the server. Your changes are kept on this device and will be sent when it is back.'}
        </span>
        <button type="button" className="link" onClick={() => retrySync()}>Try again</button>
      </div>
    );
  }
  const text = v.status === 'loading' ? 'Loading your plan…' : v.status === 'saving' ? 'Saving…' : 'All changes saved';
  return <div className={'sync sync-' + v.status} role="status">{text}</div>;
}

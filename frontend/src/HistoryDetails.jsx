import { useState } from 'react';
import { LIBRARY_FIELDS } from './libraryFields';
import { libraryUrl } from './api';

// What has happened to a library. The server keeps a snapshot of the typed
// fields per event; what *changed* is the difference between two neighbouring
// snapshots, worked out here, where the field labels are.

const LABELS = {
  ...Object.fromEntries(LIBRARY_FIELDS.map((f) => [f.name, f.label])),
  // Not a form field -- a library's places are a list of their own
  paths: 'Paths',
};
const labelFor = (name) => LABELS[name] ?? name;

const NOBODY = '#888';

function shown(value) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// A list says what came and went rather than repeating itself: "Tags:
// + reprocessed" reads, where "demo → demo, reprocessed" leaves the reader
// to spot the difference.
function listChange(from, to) {
  const before = from ?? [];
  const after = to ?? [];
  return {
    added: after.filter((value) => !before.includes(value)),
    removed: before.filter((value) => !after.includes(value)),
  };
}

// What one event changed, against the snapshot before it. The oldest event has
// nothing before it, so every field it holds is what it set.
function changes(row, previous) {
  const fields = Object.keys(row.data);
  if (!previous) {
    return fields
      .filter((name) => shown(row.data[name]) !== '—')
      .map((name) => ({ name, to: row.data[name] }));
  }
  return fields
    .filter((name) => !same(row.data[name], previous.data[name]))
    .map((name) => ({ name, from: previous.data[name], to: row.data[name] }));
}

function when(stamp) {
  // The server stores UTC without saying so, which Date would read as local
  const parsed = new Date(/[Z+]/.test(stamp) ? stamp : `${stamp}Z`);
  return Number.isNaN(parsed.getTime()) ? stamp : parsed.toLocaleString();
}

function Change({ name, from, to }) {
  if (Array.isArray(from) && Array.isArray(to)) {
    const { added, removed } = listChange(from, to);
    return (
      <li>
        {labelFor(name)}:{' '}
        {removed.map((value) => (
          <span key={`-${value}`} style={{ color: '#999', marginRight: '0.4rem' }}>
            − <span style={{ textDecoration: 'line-through' }}>{value}</span>
          </span>
        ))}
        {added.map((value) => (
          <span key={`+${value}`} style={{ marginRight: '0.4rem' }}>+ {value}</span>
        ))}
      </li>
    );
  }
  return (
    <li>
      {labelFor(name)}:{' '}
      {from !== undefined && (
        <>
          <span style={{ textDecoration: 'line-through', color: '#999' }}>{shown(from)}</span>
          {' → '}
        </>
      )}
      <span>{shown(to)}</span>
    </li>
  );
}

function Event({ row, previous }) {
  const edits = changes(row, previous);
  return (
    <li style={{ marginBottom: '0.6rem' }}>
      <div style={{ fontSize: '0.8rem' }}>
        <strong>{row.event}</strong>
        {' by '}
        {row.changed_by
          ? row.changed_by
          : <span style={{ color: NOBODY }} title="No name was given">someone</span>}
        <span style={{ color: '#666' }}> · {when(row.recorded_at)}</span>
      </div>
      {edits.length > 0 && (
        <ul style={{ margin: '0.2rem 0 0', paddingLeft: '1.1rem', fontSize: '0.78rem' }}>
          {edits.map((edit) => <Change key={edit.name} {...edit} />)}
        </ul>
      )}
    </li>
  );
}

function HistoryDetails({ lib }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  // Fetched when opened rather than with the listing: it is one request per
  // library, and most rows are never expanded.
  const toggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (rows) return;
    try {
      const res = await fetch(libraryUrl(`${lib.id}/history`));
      if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      setRows(await res.json());
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <button type="button" onClick={toggle} style={{ fontSize: '0.8rem' }}>
        {open ? 'Hide' : 'Show'} history
      </button>
      {open && (
        <div style={{ marginTop: '0.5rem' }}>
          {error && <p style={{ fontSize: '0.8rem', color: '#b42318' }}>{error}</p>}
          {!error && !rows && <p style={{ fontSize: '0.8rem', color: '#666' }}>Loading...</p>}
          {/* Every library is catalogued with a row of its own, so this is
              not reachable -- but an empty list should not be a blank box. */}
          {rows?.length === 0 && (
            <p style={{ fontSize: '0.8rem', color: '#666' }}>Nothing recorded.</p>
          )}
          {rows?.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
              {rows.map((row, i) => (
                // rows are newest first, so the one before an event in time
                // is the next one along
                <Event key={row.id} row={row} previous={rows[i + 1]} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default HistoryDetails;

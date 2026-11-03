import { useState } from 'react';
import { whoAmI, setWhoAmI } from './api';

// The name the catalog records against changes. Not a login -- see api.js --
// so this is a label people set for themselves, kept where they can see it.

const PROMPT = '#b45309';

// Picking a name. Shown in the header when someone changes theirs, and inline
// wherever a change is waiting on one.
export function NamePicker({ options = [], onDone, onCancel, autoFocus }) {
  const [draft, setDraft] = useState(whoAmI());

  const save = (value) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setWhoAmI(trimmed);
    onDone(trimmed);
  };

  // The creators already in the catalog, so the usual answer is one click and
  // nobody becomes "ZC", "zc" and "Zach" in three different months.
  return (
    <div style={{
      display: 'flex', gap: '0.4rem', alignItems: 'center',
      fontSize: '0.8rem', flexWrap: 'wrap',
    }}>
      <span>You are</span>
      <select value={options.includes(draft) ? draft : ''}
              onChange={(event) => save(event.target.value)}>
        <option value="">-- pick --</option>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
      <span>or</span>
      <input
        type="text"
        placeholder="type a name"
        value={draft}
        size={14}
        autoFocus={autoFocus}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') { event.preventDefault(); save(draft); }
          if (event.key === 'Escape' && onCancel) onCancel();
        }}
      />
      <button type="button" onClick={() => save(draft)} disabled={!draft.trim()}>Save</button>
      {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
    </div>
  );
}

function WhoAmI({ options = [] }) {
  const [name, setName] = useState(whoAmI());
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <NamePicker
        options={options}
        onDone={(picked) => { setName(picked); setEditing(false); }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const open = () => setEditing(true);

  if (!name) {
    return (
      <button type="button" onClick={open} style={{ fontSize: '0.8rem', color: PROMPT }}>
        Who are you?
      </button>
    );
  }

  return (
    <div style={{ fontSize: '0.8rem', color: '#555' }}>
      Changes recorded as <strong>{name}</strong>
      {' '}
      <button type="button" onClick={open} style={{ fontSize: '0.75rem' }}>change</button>
    </div>
  );
}

export default WhoAmI;

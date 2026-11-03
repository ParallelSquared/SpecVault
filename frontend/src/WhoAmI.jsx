import { useState } from 'react';
import { rememberedHere, setWhoAmI, whoAmI } from './api';
import { useWho } from './useWho';

// The name the catalog records against changes. Not a login -- see api.js --
// so this is a label people set for themselves, kept where they can see it.

const PROMPT = '#b45309';

// Picking a name, or forgetting the one there is. Shown in the header, and
// inline wherever a change is waiting on one.
export function NamePicker({ options = [], onDone, onCancel, autoFocus }) {
  const current = whoAmI();
  const [draft, setDraft] = useState(current);
  // Off unless it was on: the shared desktops run as one Windows account, so
  // a remembered name there is everybody's.
  const [remember, setRemember] = useState(rememberedHere);

  const save = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setWhoAmI(trimmed, remember);
    onDone(trimmed);
  };

  const forget = () => {
    setWhoAmI('');
    onDone('');
  };

  // The creators already in the catalog, so the usual answer is one click and
  // nobody becomes "ZC", "zc" and "Zach" in three different months. Picking
  // one fills the box rather than saving, so "Remember me" can be decided too.
  return (
    <div style={{ fontSize: '0.8rem' }}>
      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <span>You are</span>
        <select value={options.includes(draft) ? draft : ''}
                onChange={(event) => setDraft(event.target.value)}>
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
            if (event.key === 'Enter') { event.preventDefault(); save(); }
            if (event.key === 'Escape' && onCancel) onCancel();
          }}
        />
        <button type="button" onClick={save} disabled={!draft.trim()}>Save</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginTop: '0.3rem', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', color: '#555' }}>
          <input type="checkbox" checked={remember}
                 onChange={(event) => setRemember(event.target.checked)} />
          Remember me on this computer
        </label>
        {/* Leaving a shared desktop without leaving your name behind */}
        {current && (
          <button type="button" onClick={forget} style={{ fontSize: '0.75rem' }}>
            Forget {current}
          </button>
        )}
      </div>
    </div>
  );
}

// "Recording this as ZC. Not you?" -- shown beside the button that makes an
// edit or a deletion, which is the moment the name gets written into the
// history. With no name yet it asks for one there and then. The button itself
// belongs to whoever shows this; it should be disabled until useWho() has a
// name.
export function RecordingAs({ what = 'this', options = [] }) {
  const name = useWho();
  const [picking, setPicking] = useState(false);

  if (picking || !name) {
    return (
      <div style={{ margin: '0.25rem 0 0.5rem' }}>
        <p style={{ margin: '0 0 0.35rem', fontSize: '0.8rem' }}>
          {name ? 'Who is making this change?' : `Who is making this change? It is recorded against a name.`}
        </p>
        <NamePicker
          autoFocus
          options={options}
          onDone={() => setPicking(false)}
          onCancel={name ? () => setPicking(false) : undefined}
        />
      </div>
    );
  }

  return (
    <p style={{ margin: '0.25rem 0 0.5rem', fontSize: '0.8rem' }}>
      Recording {what} as <strong>{name}</strong>.{' '}
      <button type="button" onClick={() => setPicking(true)} style={{ fontSize: '0.75rem' }}>
        Not you?
      </button>
    </p>
  );
}

function WhoAmI({ options = [] }) {
  const name = useWho();
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <NamePicker
        options={options}
        onDone={() => setEditing(false)}
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

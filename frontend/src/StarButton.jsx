import { useEffect, useRef, useState } from 'react';
import { changeHeaders, libraryUrl } from './api';
import { useWho } from './useWho';
import { NamePicker } from './WhoAmI';

// A library's stars: how many people use it, whether you are one of them, and
// -- on hover -- who the others are, which is who to ask about it.
//
// Starting with no name asks for one first, in a popover here rather than by
// sending people to the header. No "not you?" afterwards: a star changes
// nothing about the library, and a wrong one costs nothing.

const STARRED = '#c99400';

function StarButton({ lib, creators = [], onUpdated, onError }) {
  const who = useWho();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const holder = useRef(null);
  const mine = Boolean(who) && lib.starred_by.includes(who);

  useEffect(() => {
    if (!asking) return undefined;
    const close = (event) => {
      if (!holder.current?.contains(event.target)) setAsking(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [asking]);

  // Starring is PUT and unstarring DELETE, so a double click lands where it
  // was meant to rather than undoing itself.
  const send = async (star) => {
    setBusy(true);
    try {
      const res = await fetch(libraryUrl(`${lib.id}/star`), {
        method: star ? 'PUT' : 'DELETE',
        headers: changeHeaders(),
      });
      if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      onUpdated(await res.json());
    } catch (err) {
      onError(`Could not ${star ? 'star' : 'unstar'} library #${lib.id}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const click = () => {
    if (!who) { setAsking(true); return; }
    send(!mine);
  };

  const names = lib.starred_by.join(', ');
  const title = lib.stars
    ? `Starred by ${names}${mine ? '' : '. Click to star it too.'}`
    : 'No stars yet. Star it if you use it.';

  return (
    <div ref={holder} style={{ position: 'relative' }}
         // The row underneath expands when clicked; the star is its own thing.
         onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        onClick={click}
        disabled={busy}
        title={title}
        aria-pressed={mine}
        aria-label={`${mine ? 'Unstar' : 'Star'} library ${lib.id}, ${lib.stars} stars`}
        style={{
          border: 'none', background: 'none', cursor: 'pointer', padding: '0.1rem 0.2rem',
          fontSize: '0.85rem', color: mine ? STARRED : '#777', whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: '1rem' }}>{mine ? '★' : '☆'}</span> {lib.stars}
      </button>
      {asking && (
        <div style={{
          position: 'absolute', right: 0, top: '100%', zIndex: 10, marginTop: '0.25rem',
          width: '22rem', padding: '0.5rem', background: '#fff', border: '1px solid #ccc',
          borderRadius: '6px', boxShadow: '0 2px 8px rgba(0,0,0,0.15)', textAlign: 'left',
          cursor: 'default', whiteSpace: 'normal',
        }}>
          <p style={{ margin: '0 0 0.4rem', fontSize: '0.8rem' }}>
            A star is recorded against a name. Who are you?
          </p>
          <NamePicker
            autoFocus
            options={creators}
            onDone={(name) => { setAsking(false); if (name) send(true); }}
            onCancel={() => setAsking(false)}
          />
        </div>
      )}
    </div>
  );
}

export default StarButton;

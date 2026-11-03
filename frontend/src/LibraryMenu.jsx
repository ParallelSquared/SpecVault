import { useEffect, useRef, useState } from 'react';
import { libraryUrl, changeHeaders, whoAmI } from './api';
import { NamePicker } from './WhoAmI';

// The per-row options menu: edit a library, or delete it. Deleting is behind
// a confirmation, because the row it sits on is a click target itself and a
// menu that deleted on the first click would be one stray click from doing it.

const DANGER = '#b42318';

function Menu({ lib, creators, onEdit, onDeleted, onError }) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [needName, setNeedName] = useState(false);

  const remove = async () => {
    // Deleting is recorded like any other change, so it is asked for here
    // rather than being allowed through unattributed.
    if (!whoAmI()) {
      setNeedName(true);
      return;
    }
    setNeedName(false);
    setDeleting(true);
    try {
      const res = await fetch(libraryUrl(lib.id), {
        method: 'DELETE',
        headers: changeHeaders(),
      });
      if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      onDeleted();
    } catch (err) {
      onError(`Could not delete library #${lib.id}: ${err.message}`);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div style={{
      position: 'absolute', right: 0, top: '100%', zIndex: 10, marginTop: '0.25rem',
      minWidth: confirming ? '17rem' : '10rem', padding: '0.5rem',
      maxWidth: '22rem',
      background: '#fff', border: '1px solid #ccc', borderRadius: '6px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)', textAlign: 'left', cursor: 'default',
      fontWeight: 'normal', whiteSpace: 'normal',
    }}>
      {confirming ? (
        <>
          <p style={{ margin: '0 0 0.5rem', fontSize: '0.8rem' }}>
            Delete this library from SpecVault?
          </p>
          {/* Worth saying plainly: the button sits next to a path, so "Delete"
              reads like it deletes the file. SpecVault only ever reads them. */}
          <p style={{ margin: '0 0 0.5rem', fontSize: '0.75rem', color: '#666' }}>
            The file on the share is not touched, and the entry can be brought
            back by adding the file again.
          </p>
          {needName ? (
            <div style={{
              marginBottom: '0.5rem', padding: '0.5rem', borderRadius: '4px',
              border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
            }}>
              <p style={{ margin: '0 0 0.4rem', fontSize: '0.78rem' }}>
                Deleting is recorded against a name.
              </p>
              <NamePicker autoFocus options={creators} onDone={remove}
                          onCancel={() => setNeedName(false)} />
            </div>
          ) : (
            <>
              <button type="button" onClick={remove} disabled={deleting}
                      style={{ color: DANGER, fontWeight: 600 }}>
                {deleting ? 'Deleting...' : 'Yes, delete'}
              </button>
              <button type="button" onClick={() => setConfirming(false)} disabled={deleting}
                      style={{ marginLeft: '0.5rem' }}>
                Cancel
              </button>
            </>
          )}
        </>
      ) : (
        <>
          <button type="button" onClick={onEdit}
                  style={{ width: '100%', textAlign: 'left', marginBottom: '0.3rem' }}>
            Edit Library
          </button>
          <button type="button" onClick={() => setConfirming(true)}
                  style={{ color: DANGER, width: '100%', textAlign: 'left' }}>
            Delete Library
          </button>
        </>
      )}
    </div>
  );
}

function LibraryMenu({ lib, creators = [], open, onToggle, onEdit, onDeleted, onError }) {
  const holder = useRef(null);

  // Clicking anywhere else closes it -- including on another row, which would
  // otherwise leave two menus open at once.
  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (!holder.current?.contains(event.target)) onToggle(null);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open, onToggle]);

  return (
    <div
      ref={holder}
      style={{ position: 'relative' }}
      // The row underneath expands when clicked; the menu is its own thing.
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        aria-label={`Options for library ${lib.id}`}
        aria-expanded={open}
        onClick={() => onToggle(open ? null : lib.id)}
        style={{ fontSize: '0.9rem', lineHeight: 1, padding: '0.15rem 0.4rem' }}
      >
        ⋯
      </button>
      {open && (
        <Menu lib={lib} creators={creators} onEdit={onEdit}
              onDeleted={onDeleted} onError={onError} />
      )}
    </div>
  );
}

export default LibraryMenu;

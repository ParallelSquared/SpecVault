// Where the backend is. Empty means "the same origin this page came from",
// which is how SpecVault runs both ways: deployed, one process serves this
// page and the API; in development, Vite proxies /libraries to the backend
// (see vite.config.js). Same-origin either way means no CORS, and no hostname
// baked into the built bundle -- a build that hardcoded http://127.0.0.1:8000
// works only on the machine that served it.
//
// Set VITE_API_BASE only to point at a backend somewhere else entirely.
export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export const libraryUrl = (path = '') => `${API_BASE}/libraries/${path}`;

// Who the catalog records as having made a change.
//
// There are no accounts. This is whatever the person said they were called,
// kept in this browser and sent with every request that changes a library, so
// the history can answer "who should I ask about this entry" -- which is the
// question people actually have. It is self-reported, and meant to be: it is
// not a login and must never be read as one.
//
// Per browser profile, and the shared remote desktops all run as one Windows
// account -- so there, one remembered name would be everybody's. Three things
// keep that from writing the wrong name into the history: the name lapses
// after FORGET_AFTER_HOURS without use unless the person ticks "Remember me on
// this computer"; edits and deletes show the name and ask "Not you?" before
// going through; and the server records which machine each change came from.
const WHO = 'specvault.who';

// Short, because the shared desktops are used in turns: whoever sits down
// after a break of a couple of hours is asked who they are rather than told.
// Using the name resets the clock, so someone working steadily keeps it.
export const FORGET_AFTER_HOURS = 2;
const FORGET_AFTER = FORGET_AFTER_HOURS * 60 * 60 * 1000;

// Fired when someone picks or forgets a name, so the page header and any open
// prompt show the same person.
export const WHO_CHANGED = 'specvault-who-changed';

// Storage throws rather than returning null in a browser with site data
// blocked, which should cost the name, not the page.
function read() {
  try {
    const stored = JSON.parse(localStorage.getItem(WHO));
    return stored && typeof stored.name === 'string' ? stored : null;
  } catch {
    return null; // nothing stored, storage blocked, or the old plain-text form
  }
}

function write(entry) {
  try {
    if (entry) localStorage.setItem(WHO, JSON.stringify(entry));
    else localStorage.removeItem(WHO);
  } catch {
    // Not kept; the name will be asked for again.
  }
}

export function whoAmI() {
  const stored = read();
  if (!stored) return '';
  if (!stored.remember && Date.now() > stored.until) {
    // Lapsed. Quietly: this runs while the page is drawing, and announcing
    // it would have other parts of the page redraw in the middle of that.
    write(null);
    return '';
  }
  return stored.name;
}

export function rememberedHere() {
  return Boolean(read()?.remember);
}

export function setWhoAmI(name, remember = false) {
  write(name ? { name, remember, until: Date.now() + FORGET_AFTER } : null);
  window.dispatchEvent(new Event(WHO_CHANGED));
}

// Headers for a request that changes something. Using the name counts as
// still being here, so the hours run from the last change rather than from
// when the name was picked.
export function changeHeaders(extra = {}) {
  const who = whoAmI();
  if (!who) return { ...extra };
  write({ ...read(), until: Date.now() + FORGET_AFTER });
  return { ...extra, 'X-SpecVault-User': who };
}

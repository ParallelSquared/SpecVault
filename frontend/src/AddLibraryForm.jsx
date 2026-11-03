import { useState } from 'react';
import { LIBRARY_FIELDS, FIELD_GROUPS, valueOf } from './libraryFields';
import ComboBoxField from './ComboBoxField';
import MultiComboBoxField from './MultiComboBoxField';
import { libraryUrl, changeHeaders, whoAmI } from './api';
import { NamePicker, RecordingAs } from './WhoAmI';
import { useWho } from './useWho';

// Fields the server works out from the file on save are not the form's to send
const FORM_FIELDS = LIBRARY_FIELDS.filter((f) => f.form !== false);

// Editing leaves the library's own path alone. Where a library is, and the
// other places its file is kept, are a list -- managed under Show files, not
// retyped here, where one box could only ever stand for the first of them.
const EDIT_FIELDS = FORM_FIELDS.filter((f) => f.name !== 'path');

const emptyForm = () =>
  Object.fromEntries(FORM_FIELDS.map((f) => [f.name, f.type === 'multicombobox' ? [] : '']));

// The same shape, filled in from a library the catalog already holds. Null and
// absent both become '' (or []), which is what the form controls expect.
//
// valueOf, not lib[f.name]: paths are stored share-relative, so the raw field
// is `JMod/.../report.log.txt` -- not a path any machine can open, and one the
// server refuses on the way back in because it matches no mount. The display_*
// spelling is what the person pasted and what goes back.
const formFor = (lib) =>
  Object.fromEntries(FORM_FIELDS.map((f) => {
    const value = valueOf(f, lib);
    if (f.type === 'multicombobox') return [f.name, value ?? []];
    return [f.name, value === null || value === undefined ? '' : value];
  }));

const cleanPath = (value) => {
  let v = value.trim();
  if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) {
    v = v.slice(1, -1).trim();
  }
  return v;
};

const PATH_FIELDS = new Set(['path', 'creation_log_path', 'fasta_path']);

// Same amber as the files panel uses for a copy that is not there
const MISSING = '#b45309';

// The form as the API wants it: blanks become null, empty lists too, and paths
// are tidied of the quotes and spaces that come with pasting from a file
// manager. *withoutPath* where the library's own location is not the form's to
// set -- editing an entry, or restoring one, where it is a list handled apart.
const payloadFrom = (values, withoutPath) =>
  Object.fromEntries(
    Object.entries(values)
      .filter(([name]) => !(withoutPath && name === 'path'))
      .map(([name, value]) => {
        if (Array.isArray(value)) return [name, value.length ? value : null];
        const tidied = PATH_FIELDS.has(name) && typeof value === 'string'
          ? cleanPath(value)
          : value;
        return [name, tidied === '' ? null : tidied];
      }),
  );

// Three fields to a row. Six tracks rather than three so a pair of fields can
// split a row in half (span: 3).
const GRID_TRACKS = 6;
const FIELD_SPAN = 2;

// What a creation log fills in, from either Auto-fill; anything the log does
// not say is left as it was
const withLogFields = (prev, body) => ({
  ...prev,
  creation_log_path: body.creation_log_path ?? prev.creation_log_path,
  search_algorithm: body.search_algorithm ?? prev.search_algorithm,
  software_version: body.software_version ?? prev.software_version,
  date_generated: body.date_generated ?? prev.date_generated,
  fasta_path: body.fasta_path ?? prev.fasta_path,
  source_runs: body.source_runs && body.source_runs.length ? body.source_runs : prev.source_runs,
  mbr: body.mbr === null || body.mbr === undefined ? prev.mbr : String(body.mbr),
  vendor: body.vendor ?? prev.vendor,
});

// FastAPI's `detail` is a sentence for the errors we raise ourselves -- a path
// off the share says so in words -- but a list of objects when validation
// fails. Stringifying the whole thing put raw JSON in front of the user.
const describeError = (body, status) => {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = (e.loc || []).filter((p) => p !== 'body').join('.');
        return field ? `${field}: ${e.msg}` : e.msg;
      })
      .join('; ');
  }
  return `Server responded with ${status}`;
};

// A log whose software and version were read says so; one that was found but
// not understood still says it was found, or the log field reads as untouched.
const logRead = (body) => {
  if (body.software_version) {
    return `Read the ${body.search_algorithm} ${body.software_version} log at ${body.creation_log_path}.`;
  }
  return body.creation_log_path ? `Found a log at ${body.creation_log_path}.` : '';
};

// One form, two jobs. Given a *library* it edits that one; given none it adds
// a new one. Kept together deliberately: they offer the same fields with the
// same controls and the same dropdowns, and as two components they would drift
// -- a field added to one and forgotten in the other saves on create and
// silently vanishes on edit.
function AddLibraryForm({ onLibraryAdded, fieldOptions, library, onCancel }) {
  const editing = Boolean(library);
  const fields = editing ? EDIT_FIELDS : FORM_FIELDS;
  // Every place the file is, each saying whether it is there
  const [editedPaths, setEditedPaths] = useState(() => library?.path_details ?? []);
  const [removingPath, setRemovingPath] = useState(null);
  // An edit or a removal waiting on "Recording this as ZC" being seen. The
  // shared desktops remember one name for everybody, so the name is shown at
  // the moment it is about to be written into the history, with "Not you?".
  const [confirmingEdit, setConfirmingEdit] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(null);
  const who = useWho();
  const [formData, setFormData] = useState(() => (library ? formFor(library) : emptyForm()));
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMessage, setAnalyzeMessage] = useState(null);
  const [readingLog, setReadingLog] = useState(false);
  const [logMessage, setLogMessage] = useState(null);
  // Set when saving found the file already catalogued: the entry it matched,
  // and the path that was being added, waiting on a yes.
  const [duplicate, setDuplicate] = useState(null);
  const [addingPath, setAddingPath] = useState(false);
  const [restoring, setRestoring] = useState(false);
  // Auto-fill found the file already catalogued. A heads-up, not the decision:
  // that stays at Save, where what has been typed can be offered along with it.
  const [knownFile, setKnownFile] = useState(null);
  // The file is there but would not parse as a library, so the save is
  // waiting on a yes. Held rather than acted on, because what it costs --
  // counts, modifications, library details -- is worth reading first.
  const [unreadable, setUnreadable] = useState(null);
  // The change waiting on a name being given, so the asking can happen where
  // the button was pressed: {what: 'save'} or {what: 'path', id}. A prompt
  // rendered at the foot of a long form, for a Remove button at the top of
  // it, reads as the button having done nothing at all.
  const [needName, setNeedName] = useState(null);

  const handleChange = (name, value) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  // Paths are cleaned on blur, never on change. cleanPath() trims, and trimming
  // a controlled input on every keystroke swallowed each space as it was typed:
  // "D:\\Shared Drive\\My Libs" ended up as "D:\\SharedDrive\\MyLibs".
  const handleBlur = (name) => {
    if (!PATH_FIELDS.has(name)) return;
    setFormData((prev) => {
      const value = prev[name];
      if (typeof value !== 'string') return prev;
      const cleaned = cleanPath(value);
      return cleaned === value ? prev : { ...prev, [name]: cleaned };
    });
  };


  const handleAutoFill = async () => {
    const path = cleanPath(formData.path || '');
    if (!path) {
      setAnalyzeMessage('Enter a path first.');
      return;
    }
    setAnalyzing(true);
    setAnalyzeMessage(null);
    try {
      // A creation log typed in is used as given; otherwise the server looks
      // for one where DIA-NN or JMod leaves it
      const creationLog = cleanPath(formData.creation_log_path || '') || null;
      const res = await fetch(libraryUrl('analyze'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, creation_log_path: creationLog }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.detail || 'Could not analyze file');
      }
      setFormData((prev) => ({
        ...withLogFields(prev, body),
        tags: body.tags ?? prev.tags,
        protease: body.protease ?? prev.protease,
        carbamidomethylated:
          body.carbamidomethylated === null || body.carbamidomethylated === undefined
            ? prev.carbamidomethylated
            : String(body.carbamidomethylated),
        ptms: body.ptms && body.ptms.length ? body.ptms : prev.ptms,
      }));
      setAnalyzeMessage(body.warning || 'Auto-filled from file. Review before saving.');
      // The catalog already holds these bytes. Said now, while the form is
      // still empty, rather than at Save after it has all been filled in.
      setKnownFile(body.duplicate ?? null);
      // Analyzing the file also reads its creation log, so the log's own
      // Auto-fill has nothing left to do. Its message is shown as though the
      // button had been pressed, or the log field looks like unfinished work.
      setLogMessage(body.creation_log_path ? `${logRead(body)} Review before saving.`.trim() : null);
    } catch (err) {
      setAnalyzeMessage(err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLogAutoFill = async () => {
    const path = cleanPath(formData.creation_log_path || '');
    if (!path) {
      setLogMessage('Enter a log path first.');
      return;
    }
    setReadingLog(true);
    setLogMessage(null);
    try {
      const res = await fetch(libraryUrl('analyze-log'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.detail || 'Could not read the log');
      }
      setFormData((prev) => withLogFields(prev, body));
      setLogMessage(body.warning || `${logRead(body)} Review before saving.`);
    } catch (err) {
      setLogMessage(err.message);
    } finally {
      setReadingLog(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (editing) {
      setConfirmingEdit(true);
      return;
    }
    submit();
  };

  // Split from the handler above so that answering "who are you?" can carry
  // straight on into the save the person already asked for, rather than
  // making them press the button twice.
  const submit = async ({ saveUnreadable = false } = {}) => {
    // Every change is recorded against a name, so one is asked for here --
    // at the moment it is needed, not by sending people to the header.
    if (!whoAmI()) {
      setNeedName({ what: 'save', saveUnreadable });
      return;
    }
    setNeedName(null);
    // About to find out again; the refusal re-sets it if it still applies.
    setUnreadable(null);
    setError(null);
    setSubmitting(true);

    const payload = payloadFrom(formData, editing);
    if (saveUnreadable) payload.save_unreadable = true;

    try {
      const res = await fetch(editing ? libraryUrl(library.id) : libraryUrl(), {
        method: editing ? 'PATCH' : 'POST',
        headers: changeHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      });

      const body = await res.json().catch(() => null);
      if (!res.ok) {
        // The file is already catalogued somewhere else. Not an error to
        // correct — the entry it matched is offered the path instead. Only on
        // create: an edit does not touch the path, so it cannot collide.
        if (!editing && res.status === 409 && body?.detail?.library_id) {
          setDuplicate({ ...body.detail, path: payload.path });
          return;
        }
        // The file is there but would not parse. Not corrected but confirmed:
        // a real library in a format SpecVault does not know is still worth
        // cataloguing, so long as what that costs has been said.
        if (!editing && res.status === 409 && body?.detail?.unreadable) {
          setUnreadable(body.detail);
          return;
        }
        throw new Error(describeError(body, res.status));
      }

      if (!editing) setFormData(emptyForm());
      onLibraryAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // The way back from deleting a library by mistake: add the file again, and
  // the entry it matched -- which kept its metadata, hash and paths -- returns
  // rather than being retyped as a new one.
  // *withDetails* decides whose metadata the restored entry keeps: what was
  // just typed, or what it held when it was deleted. The path goes either
  // way -- it says where the file is now, which is usually why the library is
  // being added again at all.
  const handleRestore = async (withDetails) => {
    if (!whoAmI()) {
      setNeedName({ what: 'restore', withDetails });
      return;
    }
    setNeedName(null);
    setRestoring(withDetails ? 'details' : 'asItWas');
    setError(null);
    try {
      const res = await fetch(libraryUrl(`${duplicate.library_id}/restore`), {
        method: 'POST',
        headers: changeHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          path: duplicate.path,
          details: withDetails ? payloadFrom(formData, true) : null,
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(describeError(body, res.status));
      setDuplicate(null);
      setKnownFile(null);
      setFormData(emptyForm());
      onLibraryAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setRestoring(false);
    }
  };

  // Stop recording one of the places the file is. Nothing on the share is
  // touched; the entry just stops claiming a copy that is not there, or one
  // that was pasted in by mistake.
  const handleRemovePath = async (pathId) => {
    if (!whoAmI()) return;
    setConfirmingRemove(null);
    setRemovingPath(pathId);
    setError(null);
    try {
      const res = await fetch(libraryUrl(`${library.id}/paths/${pathId}`), {
        method: 'DELETE',
        headers: changeHeaders(),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(describeError(body, res.status));
      setEditedPaths(body.path_details);
    } catch (err) {
      setError(err.message);
    } finally {
      setRemovingPath(null);
    }
  };

  const handleAddPathToExisting = async () => {
    setAddingPath(true);
    setError(null);
    try {
      const res = await fetch(libraryUrl(`${duplicate.library_id}/paths`), {
        method: 'POST',
        headers: changeHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ path: duplicate.path }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(describeError(body, res.status));
      setDuplicate(null);
      setFormData(emptyForm());
      onLibraryAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setAddingPath(false);
    }
  };

  // The paths with their own Auto-fill, shown to the right of the box
  const autoFills = {
    path: { onClick: handleAutoFill, busy: analyzing, label: 'Auto-fill from file', busyLabel: 'Analyzing...', message: analyzeMessage },
    creation_log_path: { onClick: handleLogAutoFill, busy: readingLog, label: 'Auto-fill from log', busyLabel: 'Reading log...', message: logMessage },
  };

  const renderField = (field) => (
    <div
      key={field.name}
      style={{
        display: 'flex', flexDirection: 'column', gap: '0.25rem',
        gridColumn: field.wide ? '1 / -1' : `span ${field.span || FIELD_SPAN}`,
      }}
    >
      <label style={{ fontSize: '0.85rem', fontWeight: 600 }}>
        {field.label}{field.required ? ' *' : ''}
      </label>

      {field.type === 'text' && (
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="text"
            value={formData[field.name]}
            onChange={(e) => handleChange(field.name, e.target.value)}
            onBlur={() => handleBlur(field.name)}
            required={field.required}
            style={{ flex: 1, minWidth: 0 }}
          />
          {autoFills[field.name] && (
            <button
              type="button"
              onClick={autoFills[field.name].onClick}
              disabled={autoFills[field.name].busy}
              style={{ flexShrink: 0, width: '10.5rem' }}
            >
              {autoFills[field.name].busy ? autoFills[field.name].busyLabel : autoFills[field.name].label}
            </button>
          )}
        </div>
      )}
      {autoFills[field.name]?.message && (
        <p style={{ fontSize: '0.8rem', color: '#666', margin: '0.1rem 0 0' }}>{autoFills[field.name].message}</p>
      )}

      {field.type === 'readonly' && (
        <input
          type="text"
          value={formData[field.name] || ''}
          readOnly
          placeholder="(computed automatically)"
          style={{ background: '#f2f2f2', color: '#555', cursor: 'not-allowed' }}
        />
      )}

      {field.type === 'textarea' && (
        <textarea
          value={formData[field.name]}
          onChange={(e) => handleChange(field.name, e.target.value)}
          rows={3}
        />
      )}

      {field.type === 'date' && (
        <input
          type="date"
          value={formData[field.name] || ''}
          onChange={(e) => handleChange(field.name, e.target.value)}
        />
      )}

      {field.type === 'number' && (
        <input
          type="number"
          value={formData[field.name]}
          onChange={(e) => handleChange(field.name, e.target.value === '' ? '' : Number(e.target.value))}
        />
      )}

      {field.type === 'combobox' && (
        <ComboBoxField
          label={field.label}
          value={formData[field.name]}
          options={fieldOptions[field.name] || []}
          onChange={(val) => handleChange(field.name, val)}
          required={field.required}
        />
      )}

      {field.type === 'multicombobox' && (
        <MultiComboBoxField
          label={field.label}
          values={formData[field.name]}
          options={fieldOptions[field.name] || []}
          onChange={(vals) => handleChange(field.name, vals)}
          pickExisting={field.pickExisting !== false}
        />
      )}

      {field.type === 'boolean' && (
        <select
          value={formData[field.name]}
          onChange={(e) => handleChange(field.name, e.target.value)}
        >
          <option value="">-- unknown --</option>
          <option value="true">{field.trueLabel || 'Yes'}</option>
          <option value="false">{field.falseLabel || 'No'}</option>
        </select>
      )}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} style={{ marginBottom: '2rem', maxWidth: '860px' }}>
      <h2>{editing ? `Edit Library #${library.id}` : 'Add Library'}</h2>

      {/* Auto-fill read the file and recognised it. At the top, where the
          path field and the button that found it are: at the foot of the
          form it would be a thousand pixels from anything it is about, and
          read after the typing it exists to save. */}
      {knownFile && !duplicate && (
        <div style={{
          marginBottom: '1rem', padding: '0.75rem', borderRadius: '6px',
          border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
        }}>
          <p style={{ margin: 0, fontSize: '0.85rem' }}>
            <strong>SpecVault already has this file</strong> as library
            #{knownFile.library_id}
            {knownFile.deleted ? ', which was deleted. ' : '. '}
            {knownFile.deleted
              ? 'Saving will offer to restore it, with these details or its own.'
              : knownFile.already_recorded
                ? 'That entry already lists this path, so there is nothing to add.'
                : 'Saving will offer to record this path on it. Its details are kept, not these.'}
          </p>
        </div>
      )}

      {editing && (
        // Which library this is. The paths are not fields here -- they are a
        // list, and one box could only ever stand for the first of them -- but
        // leaving them out entirely meant the form opened with nothing saying
        // what it was about.
        <div style={{
          marginTop: '-0.5rem', marginBottom: '1rem', padding: '0.6rem 0.75rem',
          background: '#f6f6f6', border: '1px solid #e2e2e2', borderRadius: '6px',
        }}>
          <div style={{ fontSize: '0.75rem', color: '#666', fontWeight: 'bold' }}>
            {editedPaths.length > 1 ? `Library file (${editedPaths.length} copies)` : 'Library file'}
          </div>
          {editedPaths.map((place) => (
            <div key={place.display} style={{
              // wraps so a removal's confirmation can sit under its own path
              display: 'flex', gap: '0.5rem', alignItems: 'baseline', marginTop: '0.2rem',
              flexWrap: 'wrap',
            }}>
              <span style={{
                fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.78rem',
                wordBreak: 'break-all', color: place.exists ? undefined : MISSING,
              }}>
                {place.display}
              </span>
              {!place.exists && (
                <span style={{ color: MISSING, fontSize: '0.72rem', flexShrink: 0 }}>
                  ⚠ not found
                </span>
              )}
              {/* The last one stays: an entry with no paths says nothing
                  about where its library is. Removing a path records no
                  copy anywhere -- the file itself is never touched. */}
              {editedPaths.length > 1 && (
                <button
                  type="button"
                  onClick={() => setConfirmingRemove(place.id)}
                  disabled={removingPath !== null || confirmingRemove !== null}
                  title="Stop recording this copy. The file is not deleted."
                  style={{ fontSize: '0.7rem', flexShrink: 0 }}
                >
                  {removingPath === place.id ? 'Removing...' : 'Remove'}
                </button>
              )}
              {confirmingRemove === place.id && (
                <div style={{
                  flexBasis: '100%', padding: '0.4rem 0.5rem', borderRadius: '4px',
                  border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
                }}>
                  <RecordingAs what="this removal" options={fieldOptions.creator || []} />
                  <button type="button" onClick={() => handleRemovePath(place.id)}
                          disabled={!who} style={{ fontSize: '0.75rem' }}>
                    Remove this copy
                  </button>
                  <button type="button" onClick={() => setConfirmingRemove(null)}
                          style={{ fontSize: '0.75rem', marginLeft: '0.5rem' }}>
                    Cancel
                  </button>
                </div>
              )}
            </div>
          ))}
          <p style={{ margin: '0.5rem 0 0', fontSize: '0.78rem', color: '#666' }}>
            {editedPaths.length > 1
              ? 'Removing a copy only stops SpecVault recording it; the file stays where it is.'
              : 'Another copy is added from the Add Library page, by saving the same file again.'}
          </p>
        </div>
      )}

      {FIELD_GROUPS.map((group) => {
        const groupFields = fields.filter((f) => f.group === group);
        // Fields of one subgroup share a row; a group without them is one grid.
        // Every row has the same tracks, so short rows line up.
        const rows = [...new Set(groupFields.map((f) => f.subgroup))]
          .map((subgroup) => [subgroup, groupFields.filter((f) => f.subgroup === subgroup)]);
        return (
          <fieldset key={group} style={{ marginBottom: '1.25rem', border: '1px solid #ddd', borderRadius: '6px', padding: '1rem' }}>
            <legend style={{ fontWeight: 'bold', padding: '0 0.5rem' }}>{group}</legend>
            {rows.map(([subgroup, fields], i) => (
              <div key={subgroup || group} style={{ marginTop: i ? '1rem' : 0 }}>
                {subgroup && (
                  <div style={{ fontSize: '0.75rem', color: '#666', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.4rem' }}>
                    {subgroup}
                  </div>
                )}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${GRID_TRACKS}, minmax(0, 1fr))`,
                  gap: '1rem',
                }}>
                  {fields.map(renderField)}
                </div>
              </div>
            ))}
          </fieldset>
        );
      })}

      {duplicate && (
        <div style={{
          marginBottom: '1rem', padding: '0.75rem', borderRadius: '6px',
          border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
        }}>
          <p style={{ margin: 0, fontWeight: 600 }}>{duplicate.message}</p>
          {duplicate.deleted ? (
            // Deleting keeps the entry, so this is an undo rather than a save:
            // nothing here has to be filled in again.
            <>
              <p style={{ margin: '0.35rem 0 0', fontSize: '0.85rem' }}>
                It is still here as library #{duplicate.library_id}
                {duplicate.paths?.length ? `, at ${duplicate.paths.join(', ')}` : ''}.
                {!duplicate.already_recorded && (
                  <> This path is recorded on it either way.</>
                )}
              </p>
              {/* Two ways, because the entry's old metadata and what has just
                  been typed are both plausibly the right answer -- and
                  quietly picking the old one threw away a filled-in form. */}
              <p style={{ margin: '0.5rem 0', fontSize: '0.85rem' }}>
                Which details should it come back with?
              </p>
              <button type="button" onClick={() => handleRestore(true)} disabled={!!restoring}>
                {restoring === 'details' ? 'Restoring...' : 'Restore with these details'}
              </button>
              <button
                type="button"
                onClick={() => handleRestore(false)}
                disabled={!!restoring}
                style={{ marginLeft: '0.5rem' }}
              >
                {restoring === 'asItWas' ? 'Restoring...' : 'Restore as it was'}
              </button>
              {needName?.what === 'restore' && (
                <div style={{ marginTop: '0.5rem' }}>
                  <p style={{ margin: '0 0 0.4rem', fontSize: '0.8rem' }}>
                    Restoring is recorded against a name.
                  </p>
                  <NamePicker
                    autoFocus
                    options={fieldOptions.creator || []}
                    onDone={() => handleRestore(needName.withDetails)}
                    onCancel={() => setNeedName(null)}
                  />
                </div>
              )}
            </>
          ) : (
            <>
              <p style={{ margin: '0.35rem 0 0', fontSize: '0.85rem' }}>
                This exact file is already recorded as library #{duplicate.library_id}
                {duplicate.paths?.length
                  ? `, at ${duplicate.paths.join(', ')}` : ''}.
              </p>
              {duplicate.already_recorded ? (
                <p style={{ margin: '0.5rem 0 0', fontSize: '0.85rem' }}>
                  That entry already lists this path, so there is nothing to add.
                </p>
              ) : (
                <>
                  <p style={{ margin: '0.5rem 0', fontSize: '0.85rem' }}>
                    Add <code style={{ background: 'none', padding: 0 }}>{duplicate.path}</code> to
                    it as another place the file is? The entry keeps its own
                    details — anything filled in here is not saved. Edit it
                    from its row if they need changing.
                  </p>
                  <button type="button" onClick={handleAddPathToExisting} disabled={addingPath}>
                    {addingPath ? 'Adding path...' : 'Add path to entry'}
                  </button>
                </>
              )}
            </>
          )}
          <button
            type="button"
            onClick={() => setDuplicate(null)}
            style={{
              marginLeft: !duplicate.deleted && duplicate.already_recorded ? 0 : '0.5rem',
              marginTop: '0.5rem',
            }}
          >
            Cancel
          </button>
        </div>
      )}

      {needName?.what === 'save' && (
        <div style={{
          marginBottom: '0.75rem', padding: '0.75rem', borderRadius: '6px',
          border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
        }}>
          <p style={{ margin: '0 0 0.5rem', fontSize: '0.85rem' }}>
            {editing ? 'This edit' : 'Adding a library'} is recorded against a
            name, so the catalog can say who to ask about it later.
          </p>
          <NamePicker
            autoFocus
            options={fieldOptions.creator || []}
            onDone={() => submit({ saveUnreadable: needName.saveUnreadable })}
            onCancel={() => setNeedName(null)}
          />
        </div>
      )}

      {/* By the Save button, which is what was just pressed. */}
      {unreadable && (
        <div style={{
          marginBottom: '0.75rem', padding: '0.75rem', borderRadius: '6px',
          border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
        }}>
          <p style={{ margin: 0, fontWeight: 600 }}>{unreadable.message}</p>
          <p style={{ margin: '0.35rem 0 0', fontSize: '0.85rem' }}>
            It is a real file and SpecVault has hashed it, so the entry can
            still be recognised later. What it will not hold:
          </p>
          <ul style={{ margin: '0.25rem 0 0.5rem', paddingLeft: '1.2rem', fontSize: '0.85rem' }}>
            {unreadable.missing.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <p style={{ margin: '0 0 0.5rem', fontSize: '0.85rem' }}>
            Save this library anyway?
          </p>
          <button type="button" onClick={() => submit({ saveUnreadable: true })}
                  disabled={submitting}>
            {submitting ? 'Saving...' : 'Yes, save it'}
          </button>
          <button type="button" onClick={() => setUnreadable(null)} disabled={submitting}
                  style={{ marginLeft: '0.5rem' }}>
            Cancel
          </button>
        </div>
      )}

      {confirmingEdit ? (
        <div style={{
          marginBottom: '0.75rem', padding: '0.75rem', borderRadius: '6px',
          border: '1px solid #f0c674', background: '#fdf6e3', color: '#8a6d1f',
        }}>
          <RecordingAs what="this edit" options={fieldOptions.creator || []} />
          <button type="button" onClick={() => { setConfirmingEdit(false); submit(); }}
                  disabled={!who || submitting}>
            {submitting ? 'Saving...' : 'Save changes'}
          </button>
          <button type="button" onClick={() => setConfirmingEdit(false)}
                  style={{ marginLeft: '0.5rem' }}>
            Not yet
          </button>
        </div>
      ) : (
        <>
          <button type="submit" disabled={submitting || !!duplicate}>
            {submitting
              ? (editing ? 'Saving...' : 'Adding...')
              : (editing ? 'Save changes' : 'Add Library')}
          </button>
          {editing && (
            <button type="button" onClick={onCancel} disabled={submitting}
                    style={{ marginLeft: '0.5rem' }}>
              Cancel
            </button>
          )}
        </>
      )}
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
    </form>
  );
}

export default AddLibraryForm;

import { useState } from 'react';
import { LIBRARY_FIELDS, FIELD_GROUPS } from './libraryFields';
import ComboBoxField from './ComboBoxField';
import MultiComboBoxField from './MultiComboBoxField';
import { libraryUrl } from './api';

// Fields the server works out from the file on save are not the form's to send
const FORM_FIELDS = LIBRARY_FIELDS.filter((f) => f.form !== false);

const emptyForm = () =>
  Object.fromEntries(FORM_FIELDS.map((f) => [f.name, f.type === 'multicombobox' ? [] : '']));

const cleanPath = (value) => {
  let v = value.trim();
  if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) {
    v = v.slice(1, -1).trim();
  }
  return v;
};

const PATH_FIELDS = new Set(['path', 'creation_log_path', 'fasta_path']);

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

const logRead = (body) =>
  body.software_version
    ? `Read the ${body.search_algorithm} ${body.software_version} log at ${body.creation_log_path}.`
    : '';

function AddLibraryForm({ onLibraryAdded, fieldOptions }) {
  const [formData, setFormData] = useState(emptyForm());
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMessage, setAnalyzeMessage] = useState(null);
  const [readingLog, setReadingLog] = useState(false);
  const [logMessage, setLogMessage] = useState(null);

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
      const fromLog = logRead(body);
      setAnalyzeMessage((body.warning || 'Auto-filled from file. Review before saving.') + (fromLog ? ' ' + fromLog : ''));
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

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const payload = Object.fromEntries(
      Object.entries(formData).map(([k, v]) => {
        if (Array.isArray(v)) return [k, v.length ? v : null];
        const value = PATH_FIELDS.has(k) && typeof v === 'string' ? cleanPath(v) : v;
        return [k, value === '' ? null : value];
      })
    );

    try {
      const res = await fetch(libraryUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ? JSON.stringify(body.detail) : `Server responded with ${res.status}`);
      }

      setFormData(emptyForm());
      onLibraryAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
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
      <h2>Add Library</h2>

      {FIELD_GROUPS.map((group) => {
        const groupFields = FORM_FIELDS.filter((f) => f.group === group);
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

      <button type="submit" disabled={submitting}>
        {submitting ? 'Adding...' : 'Add Library'}
      </button>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
    </form>
  );
}

export default AddLibraryForm;

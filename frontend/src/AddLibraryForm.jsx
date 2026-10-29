import { useState } from 'react';
import { LIBRARY_FIELDS, FIELD_GROUPS } from './libraryFields';
import ComboBoxField from './ComboBoxField';
import MultiComboBoxField from './MultiComboBoxField';
import { libraryUrl } from './api';

const emptyForm = () =>
  Object.fromEntries(LIBRARY_FIELDS.map((f) => [f.name, f.type === 'multicombobox' ? [] : '']));

const cleanPath = (value) => {
  let v = value.trim();
  if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) {
    v = v.slice(1, -1).trim();
  }
  return v;
};

const PATH_FIELDS = new Set(['path', 'creation_log_path', 'fasta_path']);

function AddLibraryForm({ onLibraryAdded, fieldOptions }) {
  const [formData, setFormData] = useState(emptyForm());
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMessage, setAnalyzeMessage] = useState(null);

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
      const res = await fetch(libraryUrl('analyze'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.detail || 'Could not analyze file');
      }
      setFormData((prev) => ({
        ...prev,
        tags: body.tags ?? prev.tags,
        precursors: body.precursors ?? prev.precursors,
        proteins: body.proteins ?? prev.proteins,
        protease: body.protease ?? prev.protease,
        carbamidomethylated:
          body.carbamidomethylated === null || body.carbamidomethylated === undefined
            ? prev.carbamidomethylated
            : String(body.carbamidomethylated),
        ptms: body.ptms && body.ptms.length ? body.ptms : prev.ptms,
      }));
      setAnalyzeMessage(body.warning || 'Auto-filled from file. Review before saving.');
    } catch (err) {
      setAnalyzeMessage(err.message);
    } finally {
      setAnalyzing(false);
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

  const renderField = (field) => (
    <div key={field.name} style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <label style={{ fontSize: '0.85rem', fontWeight: 600 }}>
        {field.label}{field.required ? ' *' : ''}
      </label>

      {field.type === 'text' && (
        <input
          type="text"
          value={formData[field.name]}
          onChange={(e) => handleChange(field.name, e.target.value)}
          onBlur={() => handleBlur(field.name)}
          required={field.required}
        />
      )}

      {field.name === 'path' && field.type === 'text' && (
        <div style={{ marginTop: '0.25rem' }}>
          <button type="button" onClick={handleAutoFill} disabled={analyzing}>
            {analyzing ? 'Analyzing...' : '⚡ Auto-fill from file'}
          </button>
          {analyzeMessage && (
            <p style={{ fontSize: '0.8rem', color: '#666', marginTop: '0.25rem' }}>{analyzeMessage}</p>
          )}
        </div>
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
    <form onSubmit={handleSubmit} style={{ marginBottom: '2rem' }}>
      <h2>Add Library</h2>

      {FIELD_GROUPS.map((group) => {
        const groupFields = LIBRARY_FIELDS.filter((f) => f.group === group);
        return (
          <fieldset key={group} style={{ marginBottom: '1.25rem', border: '1px solid #ddd', borderRadius: '6px', padding: '1rem' }}>
            <legend style={{ fontWeight: 'bold', padding: '0 0.5rem' }}>{group}</legend>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: '1rem',
            }}>
              {groupFields.map(renderField)}
            </div>
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
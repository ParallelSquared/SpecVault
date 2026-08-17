import { useState } from 'react';
import { PRIMARY_FIELDS, SECONDARY_FIELDS, FILTER_ONLY_FIELDS } from './libraryFields';

function FilterBar({ filters, onChange, fieldOptions }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [hashLookupPath, setHashLookupPath] = useState('');
  const [hashLookupStatus, setHashLookupStatus] = useState(null);
  const [hashApplied, setHashApplied] = useState(false);

  const handleChange = (name, value) => {
    onChange((prev) => ({ ...prev, [name]: value }));
  };

  const handleHashLookup = async () => {
    if (!hashLookupPath) return;
    setHashLookupStatus('Hashing...');
    try {
      const res = await fetch('http://127.0.0.1:8000/libraries/hash-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: hashLookupPath }),
      });
      const body = await res.json();
      if (!res.ok || body.error) {
        setHashLookupStatus(body.error || body.detail || `Request failed (${res.status})`);
        setHashApplied(false);
        return;
      }
      handleChange('content_hash', body.content_hash);
      setHashApplied(true);
      setHashLookupStatus(null);
    } catch (err) {
      setHashLookupStatus(err.message);
      setHashApplied(false);
    }
  };

  const renderFilterInput = (field) => {
    if (field.name === 'content_hash') {
      return (
        <div key={field.name}>
          <label style={{ display: 'block', fontSize: '0.75rem', color: '#555' }}>{field.label}</label>
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            <input
              type="text"
              placeholder="Paste a path to hash it"
              value={hashLookupPath}
              onChange={(e) => {
                setHashLookupPath(e.target.value);
                setHashApplied(false);
                handleChange('content_hash', '');
              }}
              style={{ fontSize: '0.8rem' }}
            />
            <button
              type="button"
              onClick={handleHashLookup}
              disabled={hashApplied || !hashLookupPath}
              style={{ fontSize: '0.8rem' }}
            >
              Hash & search
            </button>
          </div>
          {hashLookupStatus && (
            <span style={{ fontSize: '0.75rem', color: '#666' }}>{hashLookupStatus}</span>
          )}
        </div>
      );
    }

    return (
      <div key={field.name}>
        <label style={{ display: 'block', fontSize: '0.75rem', color: '#555' }}>{field.label}</label>

        {field.filterType === 'text' && (
          <input
            type="text"
            placeholder="Filter..."
            value={filters[field.name] || ''}
            onChange={(e) => handleChange(field.name, e.target.value)}
          />
        )}

        {(field.filterType === 'select' || field.filterType === 'multiselect') && (
          <select
            value={filters[field.name] || ''}
            onChange={(e) => handleChange(field.name, e.target.value)}
          >
            <option value="">All</option>
            {(fieldOptions[field.name] || []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        )}

        {field.filterType === 'boolean' && (
          <select
            value={filters[field.name] || 'all'}
            onChange={(e) => handleChange(field.name, e.target.value)}
          >
            <option value="all">All</option>
            <option value="exists">{field.trueLabel || 'Yes'} only</option>
            <option value="missing">{field.falseLabel || 'No'} only</option>
          </select>
        )}
      </div>
    );
  };

  const primaryFilterable = PRIMARY_FIELDS.filter((f) => f.filterType);
  const secondaryFilterable = [...SECONDARY_FIELDS.filter((f) => f.filterType), ...FILTER_ONLY_FIELDS];

  return (
    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#f7f7f7', borderRadius: '6px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem' }}>
        {primaryFilterable.map(renderFilterInput)}
      </div>

      <button
        type="button"
        onClick={() => setShowAdvanced((s) => !s)}
        style={{ marginTop: '0.75rem', fontSize: '0.85rem', background: 'none', border: 'none', color: '#4a5', cursor: 'pointer', padding: 0 }}
      >
        {showAdvanced ? '▾ Hide more filters' : '▸ More filters'}
      </button>

      {showAdvanced && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem', marginTop: '0.75rem' }}>
          {secondaryFilterable.map(renderFilterInput)}
        </div>
      )}
    </div>
  );
}

export default FilterBar;
import { useState } from 'react';
import { PRIMARY_FIELDS, SECONDARY_FIELDS, FILTER_ONLY_FIELDS } from './libraryFields';
import { sha256OfFile } from './hashFile';

function FilterBar({ filters, onChange, fieldOptions }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  // The file being looked for, by name, and how far through hashing it is
  const [hashedName, setHashedName] = useState(null);
  const [hashLookupStatus, setHashLookupStatus] = useState(null);

  const handleChange = (name, value) => {
    onChange((prev) => ({ ...prev, [name]: value }));
  };

  // Any file the person can open -- on their own disk or on the share --
  // hashed here in the browser; see hashFile.js for why not on the server.
  const handleHashLookup = async (file) => {
    if (!file) return;
    setHashedName(file.name);
    handleChange('content_hash', '');
    setHashLookupStatus('Hashing... 0%');
    try {
      const hash = await sha256OfFile(file, (done) => {
        setHashLookupStatus(`Hashing... ${Math.round(done * 100)}%`);
      });
      handleChange('content_hash', hash);
      setHashLookupStatus(null);
    } catch (err) {
      setHashLookupStatus(`Could not read ${file.name}: ${err.message}`);
    }
  };

  const clearHashLookup = () => {
    setHashedName(null);
    setHashLookupStatus(null);
    handleChange('content_hash', '');
  };

  const renderFilterInput = (field) => {
    if (field.name === 'content_hash') {
      return (
        <div key={field.name}>
          <label style={{ display: 'block', fontSize: '0.75rem', color: '#555' }}>
            {field.label}
          </label>
          {hashedName && !hashLookupStatus ? (
            <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', fontSize: '0.8rem' }}>
              <span title={filters.content_hash}>{hashedName}</span>
              <button type="button" onClick={clearHashLookup} style={{ fontSize: '0.75rem' }}>
                Clear
              </button>
            </div>
          ) : (
            <input
              type="file"
              // Whatever was picked last is gone once it has been read, so the
              // same file can be picked again after a Clear
              onChange={(e) => { handleHashLookup(e.target.files?.[0]); e.target.value = ''; }}
              disabled={hashLookupStatus?.startsWith('Hashing')}
              title="Find libraries with exactly the same contents as a file on your computer or the share"
              style={{ fontSize: '0.8rem' }}
            />
          )}
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
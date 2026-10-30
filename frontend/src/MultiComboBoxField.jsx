import { useState } from 'react';

// pickExisting: false for values that are never shared between libraries, such
// as source runs, where a list of every other library's would only be noise
function MultiComboBoxField({ label, values, options, onChange, pickExisting = true }) {
  const [inputValue, setInputValue] = useState('');
  const selected = values || [];

  const addValue = (val) => {
    const trimmed = val.trim();
    if (trimmed && !selected.includes(trimmed)) {
      onChange([...selected, trimmed]);
    }
    setInputValue('');
  };

  const removeValue = (val) => {
    onChange(selected.filter((v) => v !== val));
  };

  const availableOptions = options.filter((o) => !selected.includes(o));

  return (
    <div>
      {/* Only when there is something to show, so an empty field lines up with its row */}
      {selected.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '4px' }}>
        {selected.map((val) => (
          <span key={val} style={{ background: '#eee', padding: '2px 6px', borderRadius: '4px', maxWidth: '100%', overflowWrap: 'anywhere' }}>
            {val}{' '}
            <button
              type="button"
              onClick={() => removeValue(val)}
              style={{ border: 'none', background: 'none', cursor: 'pointer' }}
            >
              ×
            </button>
          </span>
        ))}
      </div>}

      {/* Side by side, together no wider than any other field */}
      <div style={{ display: 'flex', gap: '4px' }}>
        {pickExisting && (
          <select
            value=""
            onChange={(e) => { if (e.target.value) addValue(e.target.value); }}
            style={{ flex: 1, minWidth: 0 }}
          >
            <option value="" disabled>-- add existing --</option>
            {availableOptions.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        )}
        <input
          type="text"
          placeholder={`Add new ${label.toLowerCase()}...`}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); addValue(inputValue); }
          }}
          onBlur={() => { if (inputValue) addValue(inputValue); }}
          style={{ flex: 1, minWidth: 0 }}
        />
      </div>
    </div>
  );
}

export default MultiComboBoxField;
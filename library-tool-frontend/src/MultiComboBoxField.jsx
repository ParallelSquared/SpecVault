import { useState } from 'react';

function MultiComboBoxField({ label, values, options, onChange }) {
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
    <div style={{ display: 'inline-block' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '4px' }}>
        {selected.map((val) => (
          <span key={val} style={{ background: '#eee', padding: '2px 6px', borderRadius: '4px' }}>
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
      </div>

      <select
        value=""
        onChange={(e) => { if (e.target.value) addValue(e.target.value); }}
      >
        <option value="" disabled>-- add existing --</option>
        {availableOptions.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>{' '}

      <input
        type="text"
        placeholder={`Add new ${label.toLowerCase()}...`}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); addValue(inputValue); }
        }}
        onBlur={() => { if (inputValue) addValue(inputValue); }}
      />
    </div>
  );
}

export default MultiComboBoxField;
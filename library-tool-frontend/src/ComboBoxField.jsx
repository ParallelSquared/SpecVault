import { useState } from 'react';

function ComboBoxField({ label, value, options, onChange, required }) {
  const [adding, setAdding] = useState(false);
  const [newValue, setNewValue] = useState('');

  const handleSelectChange = (e) => {
    const val = e.target.value;
    if (val === '__add_new__') {
      setAdding(true);
      setNewValue('');
    } else {
      onChange(val);
    }
  };

  const confirmNewValue = () => {
    const trimmed = newValue.trim();
    if (trimmed) onChange(trimmed);
    setAdding(false);
  };

  if (adding) {
    return (
      <input
        type="text"
        autoFocus
        placeholder={`New ${label.toLowerCase()}`}
        value={newValue}
        onChange={(e) => setNewValue(e.target.value)}
        onBlur={confirmNewValue}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            confirmNewValue();
          }
          if (e.key === 'Escape') setAdding(false);
        }}
      />
    );
  }

  return (
    <select value={value} onChange={handleSelectChange} required={required}>
      <option value="">-- select --</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>{opt}</option>
      ))}
      {value && !options.includes(value) && (
        <option value={value}>{value} (new)</option>
      )}
      <option value="__add_new__">+ Add new...</option>
    </select>
  );
}

export default ComboBoxField;
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

  // A pasted block becomes one value per line. Windows' "Copy as path" on
  // several files, or a Mac's Option-Cmd-C, gives one path per line, and the
  // box is a single-line input: pasted as text, the line breaks vanished and
  // ten runs arrived as one. "Copy as path" also wraps each in quotes, which
  // go. A paste without line breaks is left to type into the box as usual.
  const handlePaste = (e) => {
    const text = e.clipboardData.getData('text');
    if (!/[\r\n]/.test(text)) return;
    e.preventDefault();
    const pasted = text
      .split(/\r?\n|\r/)
      .map((line) => line.trim().replace(/^(["'])(.*)\1$/, '$2').trim())
      .filter(Boolean);
    const added = [...new Set(pasted)].filter((value) => !selected.includes(value));
    if (added.length) onChange([...selected, ...added]);
    setInputValue('');
  };

  const removeValue = (val) => {
    onChange(selected.filter((v) => v !== val));
  };

  const availableOptions = options.filter((o) => !selected.includes(o));
  const listId = `options-${label.replace(/\W+/g, '-').toLowerCase()}`;

  // One box for both: typing offers the values other libraries already use,
  // and picking one adds it at once. Anything else is added on Enter or on
  // leaving the box, as a new value.
  const handleInput = (e) => {
    const typed = e.target.value;
    const picked = e.nativeEvent.inputType === 'insertReplacementText' || !e.nativeEvent.inputType;
    if (picked && availableOptions.includes(typed)) addValue(typed);
    else setInputValue(typed);
  };

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

      <input
        type="text"
        list={pickExisting ? listId : undefined}
        value={inputValue}
        onChange={handleInput}
        onPaste={handlePaste}
        title={pickExisting
          ? 'Type to add, or pick one other libraries use. Paste several at once, one per line'
          : 'Type and press Enter to add. Paste several at once, one per line'}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); addValue(inputValue); }
        }}
        onBlur={() => { if (inputValue) addValue(inputValue); }}
        style={{ width: '100%', boxSizing: 'border-box' }}
      />
      {pickExisting && (
        <datalist id={listId}>
          {availableOptions.map((opt) => <option key={opt} value={opt} />)}
        </datalist>
      )}
    </div>
  );
}

export default MultiComboBoxField;
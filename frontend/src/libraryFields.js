export const LIBRARY_FIELDS = [
  // --- Core Info ---
  // wide: a row of its own (in the Add form, and when browsing)
  // span: how many of the Add form's six tracks it takes; a field is 2, half a row is 3
  // file: a path, shown when browsing under Show files rather than in the field grid
  { name: 'path', label: 'Path', type: 'text', required: true, filterType: 'text', group: 'Core Info', primary: true, wide: true },
  { name: 'creation_log_path', label: 'Path to Creation Log', type: 'text', required: false, filterType: 'text', group: 'Core Info', primary: false, wide: true, file: true },
  { name: 'creator', label: 'Creator', type: 'combobox', required: true, filterType: 'select', group: 'Core Info', primary: true },
  { name: 'project', label: 'Project', type: 'combobox', required: false, filterType: 'select', group: 'Core Info', primary: false },
  { name: 'tags', label: 'Tags', type: 'multicombobox', required: true, filterType: 'multiselect', group: 'Core Info', primary: true },
  // Who made it and when, together
  { name: 'date_generated', label: 'Date Generated', type: 'date', required: false, filterType: null, group: 'Core Info', primary: false },
  // form: false -- counted from the file on save and shown when browsing; never typed in
  { name: 'precursors', label: 'Precursors', type: 'text', required: false, filterType: null, group: 'Core Info', primary: false, form: false },
  { name: 'proteins', label: 'Proteins', type: 'text', required: false, filterType: null, group: 'Core Info', primary: false, form: false },

  // --- Method Info --- each subgroup is a row of its own in the Add form
  { name: 'protease', label: 'Protease', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Digest', primary: true },
  {
    name: 'carbamidomethylated', label: 'Carbamidomethylated', type: 'boolean',
    required: false, filterType: 'boolean', trueLabel: 'Yes', falseLabel: 'No',
    group: 'Method Info', subgroup: 'Digest', primary: false,
  },
  { name: 'ptms', label: 'PTM(s)', type: 'multicombobox', required: false, filterType: 'multiselect', group: 'Method Info', subgroup: 'Digest', primary: false },
  { name: 'search_algorithm', label: 'Search Algorithm', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Search', primary: false },
  { name: 'software_version', label: 'Software Version', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Search', primary: false },
  {
    name: 'mbr', label: 'MBR', type: 'boolean',
    required: false, filterType: 'boolean', trueLabel: 'Yes', falseLabel: 'No',
    group: 'Method Info', subgroup: 'Search', primary: false,
  },
  { name: 'instrument', label: 'Instrument', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Acquisition', primary: false },
  { name: 'acquisition_type', label: 'Acquisition Type', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Acquisition', primary: false },
  { name: 'vendor', label: 'Vendor', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Acquisition', primary: false },
  { name: 'in_silico', label: 'In-Silico', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Prediction', primary: false },
  { name: 'finetuning', label: 'Finetuning', type: 'combobox', required: false, filterType: 'select', group: 'Method Info', subgroup: 'Prediction', primary: false },

  // --- Sample Info ---
  { name: 'species', label: 'Species', type: 'combobox', required: false, filterType: 'select', group: 'Sample Info', primary: true },
  { name: 'cell_types', label: 'Cell Type(s)', type: 'multicombobox', required: false, filterType: 'multiselect', group: 'Sample Info', primary: false },
  { name: 'tissues', label: 'Tissue(s)', type: 'multicombobox', required: false, filterType: 'multiselect', group: 'Sample Info', primary: false },


  // --- Files & Notes ---
  { name: 'fasta_path', label: 'FASTA Path', type: 'text', required: false, filterType: 'text', group: 'Files & Notes', primary: false, span: 3, file: true },
  // pickExisting: false -- runs belong to one library; offering every other library's is noise
  { name: 'source_runs', label: 'Source Runs', type: 'multicombobox', required: false, filterType: null, group: 'Files & Notes', primary: false, span: 3, file: true, pickExisting: false },
  { name: 'notes', label: 'Notes', type: 'textarea', required: false, filterType: 'text', group: 'Files & Notes', primary: false, wide: true },
];

export const FILTER_ONLY_FIELDS = [
  { name: 'content_hash', label: 'Content Hash', filterType: 'text' },
];

export const COMPUTED_FIELDS = [
  {
    name: 'path_exists', label: 'Found', filterType: 'boolean',
    default: 'exists', trueLabel: 'Found', falseLabel: 'Missing', primary: false,
  },
  { name: 'updated_at', label: 'Last Edit', filterType: null, primary: true },
  { name: 'file_format', label: 'File Format', filterType: 'select', primary: false },
  { name: 'file_size', label: 'File Size', filterType: null, primary: false },
  {
    name: 'ion_mobility', label: 'Ion Mobility', filterType: 'boolean',
    trueLabel: 'Has IM', falseLabel: 'No IM', primary: false,
  },
  { name: 'decoys', label: 'Decoys', filterType: null, primary: false },
];

export const ALL_DISPLAY_FIELDS = [...LIBRARY_FIELDS, ...COMPUTED_FIELDS];
export const PRIMARY_FIELDS = ALL_DISPLAY_FIELDS.filter((f) => f.primary);
export const SECONDARY_FIELDS = ALL_DISPLAY_FIELDS.filter((f) => !f.primary);
// The expanded row's grid: no paths, and full-width fields after the rest
export const GRID_FIELDS = [
  ...SECONDARY_FIELDS.filter((f) => !f.file && !f.wide),
  ...SECONDARY_FIELDS.filter((f) => !f.file && f.wide),
];

// The Add form's sections, in order
export const FIELD_GROUPS = ['Core Info', 'Sample Info', 'Method Info', 'Files & Notes'];

// Everything filterable, including hidden-from-display fields
export const ALL_FILTERABLE_FIELDS = [...ALL_DISPLAY_FIELDS, ...FILTER_ONLY_FIELDS];
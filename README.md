# maya-trim-aligner

**TrimAligner** by Trey McNair — a Maya tool for aligning UV shells to trim-sheet strip layouts.

Select UVs or mesh faces, open the UI, then auto-align, shift, or smart-pack shells into your strip rows.

<img width="353" height="344" alt="image" src="https://github.com/user-attachments/assets/612c3198-dd0c-4b8e-b86c-16d5044b60e3" />

## Requirements

- Autodesk Maya (2022–2026; PySide2 or PySide6)

## Install & run

1. Download or clone this repo.
2. In Maya’s Script Editor (Python):

```python
import sys
sys.path.insert(0, r"C:\path\to\maya-trim-aligner")
import TrimAligner
TrimAligner.show()
```

To create a shelf button: use the same code above, with your corrected path.

## Strip config

Click **Cfg** in the tool window to set texture size and strip heights (pixels, top → bottom).

Presets are saved next to the script in `trim_aligner_presets.json` and reload between sessions. Use the dropdown, **Save**, **Save As…**, and **Delete**.

## License

Copyright (C) 2026 Trey McNair

This program is free software under the [GNU General Public License v3.0](LICENSE).

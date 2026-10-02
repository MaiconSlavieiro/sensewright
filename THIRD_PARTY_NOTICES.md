# Third-Party Notices

This document summarizes the licenses and attributions for third-party components used by or referenced in Sensewright v2.

---

## Runtime Dependencies (Required for Players)

These libraries **must be installed separately by the player** in their Mods folder. Sensewright does not bundle or redistribute them.

### The Sims 4 Community Library (S4CL)
- **License**: Creative Commons Attribution 4.0 International (CC BY 4.0)
- **License URL**: https://creativecommons.org/licenses/by/4.0/
- **Source**: https://github.com/DeviantGameMods/Sims4CommunityLibrary
- **Reference copy in repo**: `research/s4cl/`
- **Copyright**: (c) DEVIANTGAMEMODS

> **Attribution Requirement**: Per CC BY 4.0, you must give appropriate credit, provide a link to the license, and indicate if changes were made. Sensewright credits S4CL in its documentation and mod description.

### Lot 51 Core Library
- **License**: MIT License
- **License URL**: https://opensource.org/licenses/MIT
- **Source**: https://github.com/lot51/lot51_core
- **Reference copy in repo**: `research/lot51_core/`
- **Copyright**: (c) 2022 Lot 51

> **Full License Text** (from `research/lot51_core/LICENSE`):
```
MIT License

Copyright (c) 2022 Lot 51

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Sidecar Dependencies (Python Packages)

These are installed in the sidecar's Python environment (via `pip install -r sidecar/requirements.txt`). They are **not** distributed with the mod.

| Package | License | SPDX Identifier | Repository |
|---------|---------|-----------------|------------|
| FastAPI | MIT | `MIT` | https://github.com/fastapi/fastapi |
| Uvicorn | BSD-3-Clause | `BSD-3-Clause` | https://github.com/encode/uvicorn |
| Pydantic | MIT | `MIT` | https://github.com/pydantic/pydantic |
| Tomli | MIT | `MIT` | https://github.com/hukkin/tomli |
| HTTPX | MIT | `MIT` | https://github.com/encode/httpx |
| Pytest | MIT | `MIT` | https://github.com/pytest-dev/pytest |
| Python (stdlib) | PSF-2.0 | `PSF-2.0` | https://www.python.org/ |

### License Texts (Summary)

**MIT License** (FastAPI, Pydantic, Tomli, HTTPX, Pytest):
```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

**BSD-3-Clause** (Uvicorn):
```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.
```

**PSF-2.0** (Python):
```
Python Software Foundation License Version 2
--------------------------------------------
1. This LICENSE AGREEMENT is between the Python Software Foundation
("PSF"), and the Individual or Organization ("Licensee") accessing and
otherwise using this software ("Python") in source or binary form and
its associated documentation.
...
```

---

## Build-Time Dependencies

These tools are used only during development/build and are not distributed.

| Tool | License | Purpose |
|------|---------|---------|
| `py -3.7` (Python 3.7 interpreter) | PSF-2.0 | Compile `.ts4script` bytecode |
| `python` (3.10+) | PSF-2.0 | Run build scripts (`build.py`, `build_package.py`) |
| `unpyc3` | MIT | Decompile TS4 game scripts (optional, `scripts/decompile-scripts.ps1`) |
| `make` / `nmake` | GPL-3.0+ / MIT | Build automation |
| PowerShell 5.1 | MIT | Windows helper scripts |

---

## Sensewright v2 License

**Sensewright v2** is licensed under the **MIT License**:

```
MIT License

Copyright (c) 2026 Maicon Slavieiro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Summary of License Compatibility

| Component | License | Compatible with MIT? | Notes |
|-----------|---------|---------------------|-------|
| Sensewright v2 | MIT | — | Primary license |
| S4CL | CC BY 4.0 | Yes (runtime dep) | Requires attribution; not bundled |
| Lot 51 Core | MIT | Yes (runtime dep) | Compatible; not bundled |
| FastAPI | MIT | Yes (sidecar dep) | Compatible |
| Uvicorn | BSD-3-Clause | Yes (sidecar dep) | Compatible |
| Pydantic | MIT | Yes (sidecar dep) | Compatible |
| Tomli | MIT | Yes (sidecar dep) | Compatible |
| HTTPX | MIT | Yes (sidecar dep) | Compatible |
| Pytest | MIT | Yes (dev dep) | Compatible |

All third-party licenses are permissive and compatible with Sensewright's MIT license. No copyleft (GPL) dependencies are introduced into the distributed artifacts (`.ts4script`, `.package`).

---

## Attribution in Distributed Artifacts

The built mod files (`.ts4script`, `.package`) contain:
- No S4CL or Lot 51 Core code (they are external runtime dependencies)
- Only Sensewright's own code and compiled STBL strings
- The MIT license notice is embedded in the mod's description metadata

Players installing Sensewright will see the third-party credits in:
- This `THIRD_PARTY_NOTICES.md` file (in the repo)
- The mod's description on distribution platforms (CurseForge, ModTheSims, GitHub Releases)
- The Web Studio Setup panel (About tab)
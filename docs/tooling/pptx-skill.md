# Anthropic PowerPoint skill in Kiro

## What is installed

| Item | Location | Source |
|---|---|---|
| Skill (`name: pptx`) | `.kiro/skills/pptx/` (workspace, committed) | [anthropics/skills](https://github.com/anthropics/skills/tree/main/skills/pptx), commit `e4bb5d9` (2026-11-16), unmodified |
| Same skill, user level | `~/.kiro/skills/pptx/` | Appeared during setup (not created by these steps); identical content. The workspace copy takes precedence. |

License: Apache-2.0, see `.kiro/skills/pptx/LICENSE.txt`. Keep that file with the skill.

Kiro activates the skill automatically when a request mentions a deck, slides, a presentation or a `.pptx` file. You can also type `/pptx` in chat.

## Tools the skill needs, and how they were provided on this machine

The skill assumes these are preinstalled, as they are in Anthropic's own environment. This Amazon Linux 2023 host had none of them, and there is no root access, so everything is installed under the user's home directory.

| Tool | Version | Where | How |
|---|---|---|---|
| python-pptx, Pillow, defusedxml, lxml | 1.0.2, 13.0.0, latest, latest | `~/.local/lib/python3.11/site-packages` | `python3.11 -m pip install --user` |
| pptxgenjs, react-icons, react, react-dom, sharp | 4.0.1, 5.7.0, latest, latest, 0.35.5 | `~/.local/share/pptx-node/node_modules`, linked as `~/.node_modules` so `require()` works from any folder | `npm install` |
| LibreOffice (`soffice`) | 25.8.6.2 | `~/.local/opt/libreoffice` (official AppImage, unpacked); launcher `~/.local/bin/soffice` | AppImage from appimages.libreitalia.org |
| Poppler (`pdftoppm`) | 24.08.0 | `~/.local/opt/poppler`; launcher `~/.local/bin/pdftoppm` | Amazon Linux RPMs unpacked with `rpm2cpio` |
| Missing system libraries for LibreOffice (`libX11-xcb`, `libcups`) | AL2023 packages | `~/.local/opt/runtime-libs` | unpacked RPMs, added by the `soffice` launcher |
| `python` / `python3` launchers | point to `/usr/bin/python3.11` | `~/.local/bin/python`, `~/.local/bin/python3` | The skill runs `python scripts/...`. On this host `python` did not exist and `/usr/bin/python3` is 3.9, which breaks `soffice.py`. `.bashrc` already aliased `python3` to 3.11, but aliases do not apply in subprocesses. |

`dnf` and other system tools are unaffected: they use `#!/usr/bin/python3` directly.

## Verification

All steps from the skill's QA section ran in a clean environment (no aliases):

1. Build a slide with pptxgenjs, including a react-icons icon rasterized with sharp and a bar chart.
2. `apply_theme.js`.
3. `slide_text.py` extracted the text.
4. `office/validate.py`: "All validations PASSED!"
5. `office/soffice.py --convert-to pdf`.
6. `pdftoppm -jpeg`.
7. `thumbnail.py`.

The rendered slide showed the icon, chart values and theme fonts correctly.

## Undo

```bash
rm -rf /workshop/.kiro/skills/pptx ~/.local/opt/libreoffice ~/.local/opt/LibreOffice-still.AppImage \
       ~/.local/opt/poppler ~/.local/opt/runtime-libs ~/.local/share/pptx-node ~/.node_modules
rm -f ~/.local/bin/soffice ~/.local/bin/pdftoppm ~/.local/bin/python ~/.local/bin/python3
python3.11 -m pip uninstall -y python-pptx   # Pillow, lxml and defusedxml may be used by other tools
```

The user-level copy `~/.kiro/skills/pptx` was not created by these steps. Remove it from Kiro's
**Agent Steering & Skills** panel if it is not wanted.

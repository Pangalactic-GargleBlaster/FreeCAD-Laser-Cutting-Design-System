"""Run FreeCADCmd on macOS or Windows, honoring FREECAD_CMD when set."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def freecad_command():
    candidates = [os.environ.get('FREECAD_CMD'), shutil.which('FreeCADCmd'),
                  shutil.which('freecadcmd'),
                  r'C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe',
                  '/Applications/FreeCAD.app/Contents/Resources/bin/FreeCADCmd']
    return next((candidate for candidate in candidates
                 if candidate and Path(candidate).is_file()), None)


if __name__ == '__main__':
    command = freecad_command()
    if command is None:
        raise SystemExit('FreeCADCmd not found; set FREECAD_CMD to its full path')
    arguments = sys.argv[1:]
    environment = os.environ.copy()
    if (len(arguments) == 2 and
            Path(arguments[0]).name in ('check_overlaps.py', 'audit_panel_symmetry.py') and
            arguments[1].lower().endswith('.fcstd')):
        environment['PANEL_MODEL_PATH'] = str(Path(arguments[1]).resolve())
        arguments = arguments[:1]
    raise SystemExit(subprocess.call([command, *arguments], env=environment))

# python
"""Leave the isolated Modo 16.1v9 native-preview test open for user inspection."""
from pathlib import Path
keep_open=True
source=Path(r'C:\Users\Raphael Tobar\MoonRayForModo\tools\probe_native_preview_gui.py')
exec(compile(source.read_text(),str(source),'exec'),globals())

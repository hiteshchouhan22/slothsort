#!/usr/bin/env python3
"""Create a realistically messy folder for the SlothSort demo.

Usage: python demo/make_mess.py [target-dir]   (default: demo/messy)
"""

import sys
from pathlib import Path

FILES = {
    "IMG_4021.JPG": "fake jpeg bytes",
    "Screenshot 2026-10-24 at 9.41.03 PM.png": "fake png bytes",
    "invoice_final_FINAL_v3.pdf": "%PDF-1.4 fake invoice",
    "Resume (2).docx": "fake docx bytes",
    "budget 2026 copy.xlsx": "fake spreadsheet bytes",
    "notes from call.txt": "call notes: renew the domain, water the plants",
    "backup-2025-12-31.zip": "fake zip bytes",
    "lofi beats to sort files to.mp3": "fake mp3 bytes",
    "todo_old.py": "print('sort this later')\n",
    "installer_v2.1.dmg": "fake installer bytes",
    "random download (1).bin": "mystery bytes",
    ".hidden-shame.txt": "nobody should see this",
}


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "messy"
    target.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (target / name).write_text(content)
    print(f"Created {len(FILES)} messy files in {target}")


if __name__ == "__main__":
    main()

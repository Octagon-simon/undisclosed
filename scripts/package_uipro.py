#!/usr/bin/env python3
"""
Manual packaging for the uipro skill.
Mirrors skill-creator's package_skill.py logic (zip with .skill extension)
but excludes transient/debris files (.bak, __pycache__, .pyc).
Frontmatter was validated manually against quick_validate.py criteria:
  - name/uipro valid kebab-case, description present & <1024 chars,
    only allowed frontmatter properties, no angle brackets.
"""
import sys
import zipfile
from pathlib import Path

SKILL_DIR = Path("/Users/octagon/Documents/github/eigent-theia/.agents/skills/uipro").resolve()
OUT_DIR = Path("/Users/octagon/Documents/github/eigent-theia/dist").resolve()

# Skip transient/debris files
def should_exclude(path):
    name = path.name
    if name.endswith(".bak"):
        return True
    parts = path.parts
    if "__pycache__" in parts:
        return True
    if name.endswith(".pyc"):
        return True
    return False


def main():
    if not SKILL_DIR.exists():
        print(f"ERROR: skill dir not found: {SKILL_DIR}")
        sys.exit(1)
    skill_md = SKILL_DIR / "SKILL.md"
    if not skill_md.exists():
        print("ERROR: SKILL.md not found")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    skill_filename = OUT_DIR / f"{SKILL_DIR.name}.skill"

    added = []
    with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in sorted(SKILL_DIR.rglob("*")):
            if file_path.is_file() and not should_exclude(file_path):
                arcname = file_path.relative_to(SKILL_DIR.parent)
                zipf.write(file_path, arcname)
                added.append(str(arcname))

    print(f"Packaged {len(added)} files -> {skill_filename}")
    for f in added:
        print(f"  + {f}")
    print("DONE")


if __name__ == "__main__":
    main()

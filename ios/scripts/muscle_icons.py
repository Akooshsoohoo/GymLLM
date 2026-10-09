"""Draws the muscle icons of static/muscle-icons.js as images for the iOS app: one
template SVG per group and activity in Assets.xcassets ("muscle-chest", "muscle-run"),
tinted by the view like the site's currentColor. An activity's badge glyph is a second
image ("muscle-run-glyph") laid over the first, so it can take another colour.

    python ios/scripts/muscle_icons.py     # from the repo root; rerun after a change

Runs the site's own script, with node or with the jsc that ships in macOS.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "ios/Levra/Resources/Assets.xcassets"
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
# The rest of the body behind the highlighted muscles, as on the site's poster.
BASE_OPACITY = "0.14"

DUMP = """
var out = {};
M.groups.concat(M.activities).forEach(function (x) {
  out[x.id] = M.svg(x.id, { size: 48, title: false });
});
print(JSON.stringify({ icons: out, activities: M.activities.map(function (a) { return a.id; }) }));
"""


def run_site_script() -> dict:
    node = shutil.which("node")
    if node:
        command = [node, "-e", "var M = require('./static/muscle-icons.js'), print = console.log;"]
    elif Path(JSC).exists():
        command = [JSC, "-e", "load('static/muscle-icons.js'); var M = MuscleIcons;"]
    else:
        sys.exit("Needs node, or macOS's jsc, to run static/muscle-icons.js.")
    command[-1] += DUMP
    return json.loads(
        subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    )


def plain(svg: str) -> str:
    """The browser's SVG without what an asset catalog can't read: CSS variables and
    currentColor become black, which a template image is tinted from."""
    svg = re.sub(
        r'style="fill:var\(--mi-base,currentColor\);fill-opacity:var\(--mi-base-opacity,[^)]*\)"',
        f'fill="#000" fill-opacity="{BASE_OPACITY}"',
        svg,
    )
    svg = svg.replace(
        ' style="fill:var(--mi-badge-ink,#fff);stroke:none"', ' fill="#000" stroke="none"'
    )
    svg = svg.replace('stroke="var(--mi-badge-ink,#fff)"', 'stroke="#000"')
    svg = svg.replace('"currentColor"', '"#000"')
    svg = re.sub(r' (role|data-muscle)="[^"]*"', "", svg)
    if "var(" in svg or "currentColor" in svg or "style=" in svg:
        sys.exit(f"Something in the icon is still CSS: {svg[:200]}")
    return svg


def split_glyph(svg: str) -> tuple[str, str]:
    """An activity's icon without its badge glyph, and the glyph alone in the same box."""
    start = svg.index('<g transform="translate(')
    glyph = svg[start : -len("</svg>")]
    head = svg[: svg.index(">") + 1]
    return svg[:start] + "</svg>", head + glyph + "</svg>"


def write(name: str, svg: str) -> None:
    folder = ASSETS / f"{name}.imageset"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.svg").write_text(svg + "\n")
    contents = {
        "images": [{"filename": f"{name}.svg", "idiom": "universal"}],
        "info": {"author": "xcode", "version": 1},
        "properties": {
            "preserves-vector-representation": True,
            "template-rendering-intent": "template",
        },
    }
    (folder / "Contents.json").write_text(json.dumps(contents, indent=2) + "\n")


def main() -> None:
    dumped = run_site_script()
    for old in ASSETS.glob("muscle-*.imageset"):
        shutil.rmtree(old)
    for icon, svg in dumped["icons"].items():
        svg = plain(svg)
        if icon in dumped["activities"]:
            svg, glyph = split_glyph(svg)
            write(f"muscle-{icon}-glyph", glyph)
        write(f"muscle-{icon}", svg)
    print(f"Wrote {len(dumped['icons'])} icons to {ASSETS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

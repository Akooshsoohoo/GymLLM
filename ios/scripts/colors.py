"""Builds ios/Levra/Resources/Assets.xcassets colour sets from the :root block and
the forced-dark block of static/style.css. Rerun after changing a token there."""

import json
import pathlib
import re
import sys

css = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(sys.argv[2])
light_block = css[css.index(":root {") : css.index("@media (prefers-color-scheme: dark)")]
dark_block = css[css.index(':root[data-theme="dark"]') :]
dark_block = dark_block[: dark_block.index("}")]


def tokens(block):
    found = {}
    for name, value in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", block):
        value = value.strip()
        m = re.fullmatch(r"#([0-9A-Fa-f]{6})", value)
        if m:
            h = m.group(1)
            found[name] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
            continue
        m = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", value)
        if m:
            found[name] = (int(m[1]), int(m[2]), int(m[3]), float(m[4]))
    return found


light, dark = tokens(light_block), tokens(dark_block)
# The two shadows are colours too: the log card's, and the segmented toggle's.
light["shadow-card"], dark["shadow-card"] = (60, 40, 20, 0.06), (0, 0, 0, 0.0)
light["shadow-toggle"], dark["shadow-toggle"] = (0, 0, 0, 0.08), (0, 0, 0, 0.4)


def colour(c):
    r, g, b, a = c
    return {
        "color-space": "srgb",
        "components": {
            "red": f"0x{r:02X}",
            "green": f"0x{g:02X}",
            "blue": f"0x{b:02X}",
            "alpha": f"{a:.3f}",
        },
    }


out.mkdir(parents=True, exist_ok=True)
info = {"author": "xcode", "version": 1}
(out / "Contents.json").write_text(json.dumps({"info": info}, indent=2) + "\n")
for name, value in sorted(light.items()):
    d = out / f"{name}.colorset"
    d.mkdir(exist_ok=True)
    colors = [{"idiom": "universal", "color": colour(value)}]
    colors.append(
        {
            "idiom": "universal",
            "color": colour(dark.get(name, value)),
            "appearances": [{"appearance": "luminosity", "value": "dark"}],
        }
    )
    (d / "Contents.json").write_text(json.dumps({"colors": colors, "info": info}, indent=2) + "\n")
missing = sorted(set(light) - set(dark))
print(len(light), "colour sets; no dark value for:", missing)

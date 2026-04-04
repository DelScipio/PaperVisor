import urllib.request
import sys
import os

URL = "https://raw.githubusercontent.com/google/material-design-icons/master/variablefont/MaterialSymbolsOutlined%5BFILL%2CGRAD%2Copsz%2Cwght%5D.codepoints"
OUTPUT_FILE = "papervisor/ui/components/all_icons.py"

def main():
    print(f"Fetching {URL}...")
    try:
        with urllib.request.urlopen(URL) as response:
            data = response.read().decode('utf-8')
    except Exception as e:
        print(f"Error fetching URL: {e}")
        sys.exit(1)

    icons = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            icons.append(parts[0])

    print(f"Found {len(icons)} icons.")
    
    # Write to python file
    with open(OUTPUT_FILE, "w") as f:
        f.write("# Auto-generated list of Material Symbols Outlined icons\n")
        f.write("# Source: google/material-design-icons repo\n\n")
        f.write("ALL_MATERIAL_SYMBOLS = [\n")
        for icon in icons:
            f.write(f"    '{icon}',\n")
        f.write("]\n")
    
    print(f"Wrote to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

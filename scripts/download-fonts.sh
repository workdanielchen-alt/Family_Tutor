#!/bin/bash
# Download Google Fonts for offline Docker build
# Uses Clash proxy on port 7897

PROXY="http://localhost:7897"
FONTS_DIR="web/public/fonts"
mkdir -p "$FONTS_DIR"

download_font() {
  local name="$1"
  local url="$2"
  local file="$FONTS_DIR/$name"
  if [ ! -f "$file" ]; then
    if curl -s -x "$PROXY" -o "$file" "$url"; then
      echo "OK: $name ($(wc -c < "$file") bytes)"
    else
      echo "FAIL: $name ($url)"
    fi
  else
    echo "EXISTS: $name"
  fi
}

echo "=== Plus Jakarta Sans ==="
CSS=$(curl -s -x "$PROXY" "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,200;0,300;0,400;0,500;0,600;0,700;0,800;1,200;1,300;1,400;1,500;1,600;1,700;1,800&display=swap")
echo "$CSS" | while IFS= read -r line; do
  if [[ $line =~ src:\ url\((https://[^)]+)\) ]]; then
    url="${BASH_REMATCH[1]}"
    filename=$(basename "$url" | sed 's/.*[a-f0-9]\.//')
    # Extract weight and style from context
    weight=$(echo "$line" | grep -oP 'font-weight:\s*\K\d+')
    style=$(echo "$line" | grep -oP 'font-style:\s*\K\w+')
    echo "Found: ${weight} ${style}"
  fi
done

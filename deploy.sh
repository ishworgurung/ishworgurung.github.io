#!/usr/bin/env bash
# Build the Jekyll site, regenerate read-aloud audio for posts that changed,
# sync it to S3, invalidate the CloudFront cache, and check the audio is live.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

S3_BUCKET="s3://gctl.io"
SITE_URL="https://gctl.io"
CLOUDFRONT_DISTRIBUTION_ID="E158YB5V3B1OU6"
AUDIO_PATH="assets/audio/posts"

for tool in bundle aws uv ffmpeg python3 curl; do
  command -v "$tool" >/dev/null || { echo "deploy: '$tool' is required but not installed" >&2; exit 1; }
done

# A fingerprint of the generated audio, to tell whether the generator changed anything.
audio_state() {
  find _data/audio "${AUDIO_PATH}" -type f -printf '%p %s %T@\n' 2>/dev/null | sort | sha1sum
}

echo "==> Building site"
rm -rf _site
bundle exec jekyll build

# The generator reads the built posts, so it runs after the build. It only
# re-synthesises posts whose spoken text changed (and removes audio for posts
# that dropped `audio: true`); if anything changed, build again so the site
# picks up the new audio files and timings.
echo "==> Generating read-aloud audio for new or changed posts"
before="$(audio_state)"
uv run --script _tts/generate.py --site _site
if [[ "$(audio_state)" != "${before}" ]]; then
  echo "==> Audio changed; rebuilding site"
  bundle exec jekyll build
fi

echo "==> Checking every post's audio made it into the build"
python3 -I - <<'EOF'
import json, pathlib, sys
missing = []
for meta in sorted(pathlib.Path("_data/audio").glob("*.json")):
    d = json.loads(meta.read_text())
    for key in ("src", "words"):
        f = pathlib.Path("_site") / d[key].lstrip("/")
        if not f.is_file():
            missing.append(str(f))
if missing:
    sys.exit("deploy: missing from _site:\n  " + "\n  ".join(missing))
print(f"    {len(list(pathlib.Path('_data/audio').glob('*.json')))} posts with audio, all files present")
EOF

echo "==> Syncing to ${S3_BUCKET}"
# Audio is synced on its own so it gets explicit content types: browsers need
# audio/mpeg to stream and seek the MP3s.
aws s3 sync _site "${S3_BUCKET}" --delete --exclude "${AUDIO_PATH}/*"
aws s3 sync "_site/${AUDIO_PATH}" "${S3_BUCKET}/${AUDIO_PATH}" --delete \
  --exclude "*" --include "*.mp3" --content-type "audio/mpeg"
aws s3 sync "_site/${AUDIO_PATH}" "${S3_BUCKET}/${AUDIO_PATH}" --delete \
  --exclude "*" --include "*.words.json" --content-type "application/json"

echo "==> Invalidating CloudFront distribution ${CLOUDFRONT_DISTRIBUTION_ID}"
aws cloudfront create-invalidation --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" --paths "/*"

# The player needs each MP3 served as audio/mpeg with range requests (206) for
# seeking, and each words file served as JSON.
echo "==> Checking the audio is live on ${SITE_URL}"
failed=0
for meta in _data/audio/*.json; do
  [[ -e "${meta}" ]] || continue
  read -r src words < <(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["src"], d["words"])' "${meta}")
  mp3="$(curl -s -o /dev/null -r 0-1023 -w '%{http_code} %{content_type}' "${SITE_URL}${src}")"
  wj="$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "${SITE_URL}${words}")"
  if [[ "${mp3}" == "206 audio/mpeg"* && "${wj}" == "200 application/json"* ]]; then
    echo "    ok   ${src}"
  else
    echo "    FAIL ${src} -> ${mp3}; ${words} -> ${wj}" >&2
    failed=1
  fi
done
if (( failed )); then
  echo "deploy: some audio is not being served correctly (see above)" >&2
  exit 1
fi

echo "==> Done"

#!/usr/bin/env bash
# Installs Playwright's Chromium for the Amazon.ae readers.
# No "--with-deps": the runner already has Chromium's system libraries, and on 5 Nov the only extra packages
# (fonts, which the reader does not even load) took more than 7 min to download from the Ubuntu mirror, and the
# killed apt-get kept its lock so the retries failed. System libraries are installed only if Chromium cannot start.
set -u
pip install -q playwright || { sleep 20; pip install -q playwright; } || exit 1
for i in 1 2 3; do
  timeout 300 playwright install chromium && break
  echo "Chromium download failed, try $i of 3"; sleep 15
  [ "$i" = 3 ] && exit 1
done
if python3 -c "from playwright.sync_api import sync_playwright as s; p=s().start(); b=p.chromium.launch(); b.close(); p.stop()"; then
  echo "Chromium ready."; exit 0
fi
echo "Chromium does not start: installing its system libraries"
sudo env "PATH=$PATH" timeout 900 playwright install-deps chromium || exit 1
python3 -c "from playwright.sync_api import sync_playwright as s; p=s().start(); b=p.chromium.launch(); b.close(); p.stop()" && echo "Chromium ready."

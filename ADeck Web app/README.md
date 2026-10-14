# ADeck Web app

This folder is the local UI served by `deck.py` at `http://127.0.0.1:8765`.

For install, daily use, System page, and troubleshooting, see the root [README.md](../README.md).

```text
index.html             UI shell
script.js              profiles, slots, System page, save/sync
style.css              layout + themes
manifest.webmanifest   installable app window
sw.js                  app-shell cache (never caches /api)
```

Open this UI through the ADeck service — not as a raw `file://` page.

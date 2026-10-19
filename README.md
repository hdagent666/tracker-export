# Tracker Export

Bounce **per-channel stems** and **labeled samples** out of any tracker module
(`.mod`, `.s3m`, `.xm`, `.it`, and ~90 other formats via libxmp).

Given `song.mod`, it creates:

```
song_export/
    song.mod              exact copy of your input
    mix.wav               full stereo mix (44.1 kHz 16-bit)
    stems/
        ch01.wav …        one stereo bounce per tracker channel
    samples/
        01_kick.wav …     every sample as 16-bit WAV, named after the
                          sample's label in the module, with loop points
                          embedded (smpl chunk) for your sampler
    manifest.txt          what everything is
```

Sample WAVs are written at each format's native rate (MOD: 8287 Hz, base
note C-2 — the classic Amiga rate; XM/S3M/IT: 8363 Hz, base note C-4), with
the unity note in the smpl chunk so any sampler tunes them correctly.

## Requirements

The **libxmp** shared library (playback + sample decoding engine):

| OS      | Install                          |
|---------|----------------------------------|
| macOS   | `brew install libxmp`            |
| Ubuntu/Debian | `sudo apt install libxmp4` |
| Fedora  | `sudo dnf install libxmp`        |
| Arch    | `sudo pacman -S libxmp`          |

Python 3.9+ required. No other dependencies — the GUI uses tkinter (ships
with Python; on some Linux distros install `python3-tk`).

## Install

```bash
cd tracker-export
pip install .
```

This gives you two commands:

- `tracker-export-gui` — the desktop app (file picker, options, progress bar)
- `tracker-export` — the command-line version

Or run without installing:

```bash
pip install -e .          # editable, for hacking on it
python -m tracker_export.cli song.mod
```

## GUI

The GUI wears a FastTracker II theme: dark slate panels, chunky beveled
buttons, and a pattern-editor style log (green data lines, red skips).

Launch `tracker-export-gui`, build a queue with **Add files** or
**Add folder** (crawls the folder and all subfolders for modules),
choose an output folder (blank = an export folder next to each module),
tick stems/samples, hit **Export**. The whole queue is exported as one
batch; files that fail to load are logged and skipped, not fatal.
Use **Show last export** when it finishes to jump straight to the files.

## CLI

```bash
tracker-export song.mod
tracker-export song.xm -o ~/Desktop --sr 48000
tracker-export song.it --no-stems        # samples only
tracker-export song.s3m --info           # print module info, don't export

# Batch: many files at once
tracker-export a.mod b.xm c.s3m -o ~/Exports

# Batch: crawl a whole directory tree for modules
tracker-export ~/ModArchive -o ~/Exports
tracker-export ~/ModArchive --flat       # top level only, no subfolders
```

## macOS app bundle

### Build on GitHub (no Mac tooling needed locally)

Push this repo to GitHub and the **Build macOS app** workflow
(`.github/workflows/build-macos.yml`) runs on an Apple Silicon runner:

1. Push to `main` (or go to **Actions → Build macOS app → Run workflow**).
2. When it finishes, open the run and download the **TrackerExport-macOS**
   artifact — a zip containing `Tracker Export.app` with libxmp bundled
   inside, so it runs on Macs without brew libxmp.
3. Unzip and drag the app to Applications.

Pushing a version tag (`git tag v1.0.0 && git push --tags`) also attaches
the zip to a GitHub Release for a permanent download link.

By default the app is **ad-hoc signed**: it runs on your Mac, but
Gatekeeper will ask on first launch — right-click the app → **Open**.

### Proper signing + notarization (optional)

With an Apple Developer Program account ($99/yr), the same workflow can
produce a Developer ID signed, notarized app that opens with a plain
double-click anywhere. Add these repo secrets
(**Settings → Secrets and variables → Actions**):

| Secret | What it is |
|---|---|
| `DEVELOPER_CERT_P12` | Base64 of your exported Developer ID Application certificate (.p12) |
| `DEVELOPER_CERT_PASSWORD` | The password you set when exporting the .p12 |
| `APPLE_ID` | Your Apple ID email |
| `APPLE_TEAM_ID` | Your 10-character Team ID (developer.apple.com → Membership) |
| `APPLE_APP_PASSWORD` | An app-specific password from appleid.apple.com |

Export the certificate from Keychain Access (right-click the Developer ID
Application cert → Export → .p12), then base64 it:
`base64 -i cert.p12 | pbcopy` and paste as the secret value.
No secrets → the workflow automatically falls back to ad-hoc signing.

### Build on a Mac instead

```bash
./build-macos-app.sh
```

Requires Xcode command-line tools, `brew install libxmp`, and
`pip install pyinstaller`. The script bundles libxmp inside the app, so it
runs on Macs that don't have libxmp installed. The finished app lands in
`dist/`.

## Notes

- Mix/stems render at 44.1 kHz 16-bit stereo by default (`--sr` to change).
- Renders stop at the module's end or first loop; a 20-minute safety cap
  applies (`--max-seconds`).
- Sample labels come from the module's sample names, falling back to
  instrument names, then `sample_NN`.

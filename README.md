# Party playlist downloader

Searches YouTube for each song in `songs.txt` and saves it as an MP3 using
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Setup

1. Install ffmpeg (used to convert audio to MP3):
   - macOS: `brew install ffmpeg`
   - Windows: `winget install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
2. Install the Python dependency: `pip install -r requirements.txt`

## Usage

```bash
python download_songs.py --dry-run    # preview which YouTube video each song matches
python download_songs.py              # download everything into ./music
python download_songs.py my_list.txt -o party_music --bitrate 320
```

Each section of the list (`1. Gabby / Arrival / Theme Music`, ...) gets its own
folder, and files are numbered in playlist order. `music/links.csv` records the
YouTube video chosen for every song, so you can check for wrong matches. Re-running
skips songs that are already downloaded.

## Even volume

Every song is volume-normalized to the same loudness (-14 LUFS by default, the
level Spotify and YouTube use) with ffmpeg's two-pass EBU R128 `loudnorm` filter,
so nothing is suddenly much louder or quieter than the song before it.

```bash
python download_songs.py --loudness -11      # louder target (closer to 0 = louder)
python download_songs.py --no-normalize      # keep each song's original volume
python download_songs.py --normalize-only music   # even out MP3s you already have
```

`--normalize-only` works on any folder of MP3s and keeps their tags (it re-encodes
them, so run it once rather than repeatedly).

Only download music you have the rights to use, and follow YouTube's Terms of Service.

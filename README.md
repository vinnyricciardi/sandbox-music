# Party playlist downloader

Searches YouTube for each song in `songs.txt` and saves it as an MP3 using
[yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Setup

1. Install ffmpeg (converts audio to MP3) and Deno (YouTube downloads need a
   JavaScript runtime; Node.js also works if you already have it):
   - macOS: `brew install ffmpeg deno`
   - Windows: `winget install ffmpeg` and `winget install DenoLand.Deno`
   - Linux: `sudo apt install ffmpeg`, then `curl -fsSL https://deno.land/install.sh | sh`
2. Install the Python dependency: `pip install -U -r requirements.txt`

## Troubleshooting "Video unavailable"

If many downloads fail with "video unavailable" (or "not available"):

1. Update yt-dlp, since YouTube changes often: `pip install -U "yt-dlp[default]"`
2. Make sure Deno or Node.js is installed (see Setup). The script warns at startup
   if it can't find either one.
3. If the error mentions "Sign in to confirm you're not a bot", or a video is
   age-restricted, borrow your browser's YouTube login:
   `python download_songs.py --from-csv playlist.csv --cookies-from-browser chrome`
   (or `firefox`, `safari`, `edge`).

Rerunning is safe: songs that already downloaded are skipped.

## Usage

The recommended way is to review the links first, then download:

```bash
python download_songs.py --dry-run              # 1. search, save matches to playlist.csv
#   2. open playlist.csv in Excel / Google Sheets / Numbers and fix any links
python download_songs.py --from-csv playlist.csv   # 3. download exactly those links
```

Or search and download in one go: `python download_songs.py` (or
`python download_songs.py my_list.txt -o party_music --bitrate 320`).

### Reviewing links in playlist.csv

| column | what it's for |
| --- | --- |
| `section` | folder the song is saved in |
| `song` | used for the file name and the MP3's title/artist tags |
| `url` | **the YouTube link that gets downloaded — edit this one** |
| `youtube_title`, `channel`, `length` | what the search picked, to help you spot wrong matches |
| `option_2` … `option_4` | the next-best results with their links, for quick swaps |

- Wrong video? Paste a better link into `url` (any YouTube link works).
- Don't want a song? Delete the row. Want a different order? Move rows around:
  files are numbered in the order of the CSV.
- A row with an empty `url` is skipped.
- `--dry-run` won't overwrite an existing `playlist.csv`, so your edits are safe.
  Use `--overwrite` to search again from scratch.

### Helping the search with hints

In `songs.txt`, anything after a `|` is added to the YouTube search but not used for
the file name or tags. Use it for the movie or show a song is from, or a version you
want:

```
Pinching In - Gabby's Dollhouse | Gabby's Dollhouse The Movie
Let It Go - Idina Menzel | Frozen
Push It - Salt-N-Pepa | radio edit
```

### How songs are matched

For each song the script compares the top 8 YouTube results (`--candidates` to change)
and prefers the plain studio track: YouTube Music "Artist - Topic" uploads, "official
audio" and lyric videos. It avoids movie scenes, clips, trailers, covers, live versions,
karaoke, remixes, sped-up/hour-long loops, and anything much too short or long to be
the song, alternate versions (reprises, translated or tour versions), and other
singers' versions. The song title has to appear in the video title. Picks that
score poorly are marked `check: weak match` in the `status` column, so start
your review there.

Each section of the list (`1. Gabby / Arrival / Theme Music`, ...) gets its own
folder. After downloading, `music/links.csv` records the link used for every song and
whether it worked. Re-running skips songs that are already downloaded.

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

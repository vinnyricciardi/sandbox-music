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

## Making a YouTube playlist

`make_playlist.py` turns `playlist.csv` into a YouTube playlist, in the same order.

**Quick, no setup:**

```bash
python make_playlist.py playlist.csv --open
```

This opens links that play your songs as a temporary playlist (50 songs per link).
It uses an unofficial YouTube link format that may stop working without notice.
If a list shows fewer songs than expected, use smaller links with `--per-link 20`.
To try keeping a list, sign in and look for **Save** in the playlist panel. If it
isn't there, change `www.youtube.com` to `music.youtube.com` in the address bar and
look for **Save** there. This isn't officially supported, so use `--create` if you
want a reliable playlist.

**A real playlist saved in your account (YouTube Data API):**

One-time setup (about 10 minutes):

1. `pip install -r requirements-playlist.txt`
2. Go to <https://console.cloud.google.com/>, create a project, then under
   **APIs & Services → Library** enable **YouTube Data API v3**.
3. Under **APIs & Services → OAuth consent screen**, choose **External**, fill in the
   app name and your email, and add your own Google account under **Test users**.
4. Under **APIs & Services → Credentials**, choose **Create credentials → OAuth client
   ID → Desktop app**, then download the JSON and save it next to the script as
   `client_secret.json`. It is git-ignored; don't share it.

Then:

```bash
python make_playlist.py playlist.csv --create "Birthday Party"            # private by default
python make_playlist.py playlist.csv --create "Birthday Party" --privacy unlisted
```

The first run opens your browser to sign in. Google will warn that the app isn't
verified. That's expected for your own test app, so choose **Continue**. Your login is
remembered in `youtube_token.json` (also git-ignored).

### "Access blocked" when signing in

The message under "Access blocked" says which fix you need:

- **"has not completed the Google verification process" / Error 403: access_denied.**
  The Google account you signed in with isn't a test user. In Google Cloud, open
  **Google Auth Platform → Audience** (older consoles: **OAuth consent screen**). Make
  sure **Publishing status** is **Testing**, then under **Test users** click **Add users**
  and add the exact Gmail address you sign in with. Wait a minute, then run the script
  again.
  - If you have several Google accounts, the browser may pick the wrong one. Choose
    the test-user account in the account picker.
  - If your YouTube channel is a Brand Account, add the personal Gmail you log in
    with, then pick the channel after signing in.
- **"Your admin" / "your organization" / admin_policy_enforced.** You signed in with a
  work or school Google account whose admin blocks unverified apps. Use a personal
  Gmail account instead.
- **Error 400: redirect_uri_mismatch.** The OAuth client was created as a "Web
  application". Create a new one of type **Desktop app** and download its JSON. The
  script now checks for this and tells you.
- **"YouTube Data API v3 has not been used in project … or it is disabled."** Enable it
  under **APIs & Services → Library**.

If you changed accounts or settings, delete `youtube_token.json` before trying again.

YouTube's free API quota allows about 200 songs a day. If it runs out, the script
prints a command with `--playlist-id` to finish the next day. Songs already in the
playlist are skipped, so rerunning it is safe.

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

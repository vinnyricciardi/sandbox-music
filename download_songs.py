#!/usr/bin/env python3
"""Search YouTube for each song in a list and save it as an MP3.

Usage:
    python download_songs.py --dry-run               # 1. search, write playlist.csv to review
    python download_songs.py --from-csv playlist.csv # 2. download exactly the links in the CSV
    python download_songs.py                         # search and download in one go
    python download_songs.py my_list.txt -o out      # custom list / output folder
    python download_songs.py --normalize-only music  # just even out volume of existing MP3s

Reviewing links: --dry-run saves every match to playlist.csv (section, song, url,
the video's title/channel/length, and a few other options). Open it in Excel or
Google Sheets, paste a better link into the "url" column for any wrong match,
delete rows you don't want, then run --from-csv. Rows with an empty url are skipped.

Song list format (see songs.txt):
    1. Section Name          <- starts a section (saved as "01 - Section Name/")
    Title - Artist           <- one song per line
    Title - Artist | Movie   <- text after "|" only helps the search (not in the file name)
    # comment                <- ignored

Every MP3 is volume-normalized to the same loudness (default -14 LUFS, the level
Spotify and YouTube use) with ffmpeg's two-pass EBU R128 "loudnorm" filter, so
songs play back at a consistent volume. Use --no-normalize to turn this off.

Requires: pip install yt-dlp   and   ffmpeg on your PATH.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run: pip install -r requirements.txt")

SECTION_RE = re.compile(r"^(\d+)\.\s+(.+)$")
UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def safe_name(text):
    """Make a string safe to use as a file or folder name."""
    return UNSAFE_CHARS_RE.sub("-", text).strip(" .")


def parse_song_list(path):
    """Return a list of (section_folder, song, search_hint) tuples."""
    songs = []
    section = ""
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = SECTION_RE.match(line)
        if match:
            section = f"{int(match.group(1)):02d} - {safe_name(match.group(2))}"
            continue
        song, _, hint = line.partition("|")
        songs.append((section, song.strip(), hint.strip()))
    return songs


def measure_loudness(path, target):
    """First loudnorm pass: analyse the file and return ffmpeg's measurements."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", str(path),
        "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
        "-vn", "-f", "null", "-",
    ]
    stderr = subprocess.run(cmd, capture_output=True, text=True, check=True).stderr
    # The measurements are the last JSON object ffmpeg prints.
    return json.loads(stderr[stderr.rindex("{"):stderr.rindex("}") + 1])


def encode_mp3(src, dst, bitrate, target=None, tags=None):
    """Encode src to an MP3 at dst, normalizing loudness to `target` LUFS if given."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn"]
    if target is not None:
        m = measure_loudness(src, target)
        cmd += ["-af", (
            f"loudnorm=I={target}:TP=-1.5:LRA=11"
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true"
        )]
    # loudnorm resamples internally, so set the output rate explicitly.
    cmd += ["-ar", "44100", "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    for key, value in (tags or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd.append(str(dst))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def song_tags(query):
    """Guess title/artist tags from a "Title - Artist" line."""
    title, _, artist = query.partition(" - ")
    return {"title": title.strip(), "artist": artist.strip()} if artist else {"title": query}


def normalize_folder(folder, bitrate, target):
    """Re-encode every MP3 under `folder` so they all have the same loudness."""
    files = sorted(Path(folder).rglob("*.mp3"))
    if not files:
        sys.exit(f"No MP3 files found in {folder}")
    for index, path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] {path}")
        tmp = path.with_name(path.stem + ".normalizing.mp3")
        try:
            # -map_metadata keeps the existing tags.
            encode_mp3(path, tmp, bitrate, target)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                 "-i", str(tmp), "-i", str(path), "-map", "0:a", "-map_metadata", "1",
                 "-codec", "copy", str(path.with_suffix(".tagged.mp3"))],
                check=True, capture_output=True,
            )
            path.with_suffix(".tagged.mp3").replace(path)
        except subprocess.CalledProcessError as err:
            print(f"    failed: {(err.stderr or '').strip()[-300:]}")
        finally:
            tmp.unlink(missing_ok=True)
            path.with_suffix(".tagged.mp3").unlink(missing_ok=True)


# Words in a video title that suggest it isn't the plain studio song, and how much
# each one counts against it. Ignored when the word is part of the song line itself.
PENALTIES = {
    "scene": 10, "clip": 10, "trailer": 10, "teaser": 10, "episode": 10, "full movie": 10,
    "behind the scenes": 10, "reaction": 10, "tutorial": 10, "review": 8, "compilation": 8,
    "cover": 8, "karaoke": 8, "instrumental": 8, "parody": 8, "fan made": 8, "fanmade": 8,
    "sped up": 8, "slowed": 8, "nightcore": 8, "8d": 8, "1 hour": 8, "10 hours": 8, "loop": 6,
    "live": 5, "remix": 5, "mashup": 5, "acapella": 5, "a cappella": 5, "piano": 4,
    "lyrics translation": 4, "dance video": 2, "music video": 1, "official video": 1,
    "reprise": 8, "pitched": 8, "broadway": 6, "end credits": 6, "end title": 6, "score": 4,
    "sing along": 1,
    # Translated versions of soundtrack songs.
    "spanish": 6, "espanol": 6, "tagalog": 6, "french": 6, "german": 6, "italian": 6,
    "portuguese": 6, "japanese": 6, "latino": 6,
}
# "(Xyz Version)" usually means an alternate take, except for these.
OK_VERSIONS = {"single", "soundtrack", "album", "radio", "original", "film", "movie", "studio"}
VERSION_RE = re.compile(r" (\w+) version ")
# Words that suggest just the song (art tracks, official audio, lyric videos).
BONUSES = {"official audio": 5, "audio": 3, "lyric": 3, "lyrics": 3, "official": 1}


def normalize_text(text):
    # Punctuation (including curly quotes) becomes a space, then accents are dropped.
    text = re.sub(r"[\W_]+", " ", (text or "").lower())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " " + " ".join(text.split()) + " "


def score_result(song, entry, position, hint=""):
    """Higher is better: how likely `entry` is the plain studio version of `song`."""
    title = normalize_text(entry.get("title"))
    channel = normalize_text(entry.get("channel") or entry.get("uploader"))
    wanted = normalize_text(f"{song} {hint}")
    score = -0.5 * position  # small preference for YouTube's own ranking

    for word, weight in PENALTIES.items():
        if f" {word} " in title and f" {word} " not in wanted:
            score -= weight
    for match in VERSION_RE.finditer(title):
        if match.group(1) not in OK_VERSIONS and f" {match.group(0).strip()} " not in wanted:
            score -= 5
    for word, weight in BONUSES.items():
        if f" {word} " in title:
            score += weight
    # "Artist - Topic" channels are YouTube Music's auto-uploaded studio tracks.
    if channel.endswith(" topic "):
        score += 6
    elif "vevo" in channel:
        score += 2

    # The song title must appear in the video title; a big official channel posting
    # a different song from the same movie is still the wrong song.
    song_title, _, artist = song.partition(" - ")
    song_words = [w for w in normalize_text(song_title).split() if w not in {"the", "a", "an"}]
    found = sum(f" {w} " in title for w in song_words) / len(song_words) if song_words else 0
    score += 6 * found
    if found < 0.6:
        score -= 12

    # Credited artists in the title or channel (avoids other singers' versions).
    artist_words = [w for w in normalize_text(artist).split() if w not in {"the", "and", "cast", "feat", "ft"}]
    if artist_words:
        score += 4 * sum(f" {w} " in title + channel for w in artist_words) / len(artist_words)

    duration = entry.get("duration")
    if duration:
        if duration < 60:
            score -= 12
        elif duration < 90:
            score -= 8
        elif duration > 900:
            score -= 15
        elif duration > 480:
            score -= 6
    return score


def format_duration(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}" if seconds else ""


def entry_url(entry):
    url = entry.get("webpage_url") or entry.get("url") or ""
    if url.startswith("http"):
        return url
    video_id = entry.get("id") or url
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


def find_videos(ydl, song, candidates, hint=""):
    """Search YouTube and return results best-first as (score, entry) pairs."""
    query = " ".join(part for part in (song, hint, "official audio") if part)
    info = ydl.extract_info(f"ytsearch{candidates}:{query}", download=False)
    entries = [e for e in (info.get("entries") or []) if e]
    ranked = [(score_result(song, e, i, hint), e) for i, e in enumerate(entries)]
    return sorted(ranked, key=lambda pair: pair[0], reverse=True)


# Best matches scoring below this get flagged in the CSV for a manual check.
WEAK_MATCH_SCORE = 5

CSV_FIELDS = ["section", "song", "url", "youtube_title", "channel", "length",
              "option_2", "option_3", "option_4", "status"]


def search_songs(songs, candidates):
    """Find the best YouTube match for each (section, song, hint). Returns playlist rows."""
    rows = []
    search_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(search_opts) as searcher:
        for index, (section, query, hint) in enumerate(songs, start=1):
            print(f"[{index}/{len(songs)}] {query}" + (f"  ({hint})" if hint else ""))
            row = {"section": section, "song": query, "url": "", "youtube_title": "", "channel": "",
                   "length": "", "option_2": "", "option_3": "", "option_4": "", "status": ""}
            rows.append(row)
            try:
                ranked = find_videos(searcher, query, candidates, hint)
            except yt_dlp.utils.DownloadError as err:
                print(f"    search failed: {err}")
                row["status"] = "search failed"
                continue
            if not ranked:
                print("    no results")
                row["status"] = "not found"
                continue

            best_score, best = ranked[0]
            row.update(url=entry_url(best), youtube_title=best.get("title") or "",
                       channel=best.get("channel") or best.get("uploader") or "",
                       length=format_duration(best.get("duration")),
                       status="found" if best_score >= WEAK_MATCH_SCORE else "check: weak match")
            # A few runners-up, so a wrong match is easy to swap out.
            for n, (_, e) in enumerate(ranked[1:4], start=2):
                row[f"option_{n}"] = f"{e.get('title')} [{format_duration(e.get('duration'))}] {entry_url(e)}"
            print(f"    -> {row['youtube_title']} ({row['channel']}, {row['length']})\n       {row['url']}")
            if row["status"] != "found":
                print("       (weak match, please check this one)")
    return rows


def write_playlist_csv(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel shows accented characters correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_playlist_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"song", "url"} - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"{path} needs these columns: {', '.join(sorted(missing))}")
        rows = []
        for raw in reader:
            row = {k: (raw.get(k) or "").strip() for k in CSV_FIELDS}
            if row["song"]:
                row["section"] = safe_name(row["section"]) if row["section"] else ""
                rows.append(row)
        return rows


def download_rows(rows, output, bitrate, target):
    """Download each row's url to an MP3, numbered in row order. Updates row["status"]."""
    for index, row in enumerate(rows, start=1):
        query, url = row["song"], row["url"]
        print(f"[{index}/{len(rows)}] {query}")
        if not url:
            print("    no link, skipping")
            row["status"] = row["status"] if row["status"] in ("search failed", "not found") else "no link"
            continue

        folder = Path(output) / row["section"]
        folder.mkdir(parents=True, exist_ok=True)
        mp3_path = folder / f"{index:02d} - {safe_name(query)}.mp3"
        if mp3_path.exists():
            print("    already downloaded, skipping")
            row["status"] = "skipped (exists)"
            continue

        # Download the original audio, then normalize and convert it to MP3 in a
        # single ffmpeg encode so quality is only lost once.
        download_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(mp3_path.with_suffix("")) + ".source.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        source = None
        try:
            with yt_dlp.YoutubeDL(download_opts) as downloader:
                info = downloader.extract_info(url, download=True)
                source = Path(info["requested_downloads"][0]["filepath"])
                row["youtube_title"] = row["youtube_title"] or info.get("title") or ""
            encode_mp3(source, mp3_path, bitrate, target, song_tags(query))
            print(f"    saved {mp3_path}")
            row["status"] = "downloaded"
        except yt_dlp.utils.DownloadError as err:
            print(f"    download failed: {err}")
            row["status"] = "download failed"
        except subprocess.CalledProcessError as err:
            print(f"    converting to MP3 failed: {(err.stderr or '').strip()[-300:]}")
            mp3_path.unlink(missing_ok=True)
            row["status"] = "convert failed"
        finally:
            if source:
                source.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("song_list", nargs="?", default="songs.txt", help="text file with one song per line")
    parser.add_argument("-o", "--output", default="music", help="folder to save MP3s into (default: music)")
    parser.add_argument("--bitrate", default="192", help="MP3 bitrate in kbps (default: 192)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only search; save the matches to a CSV you can review and edit")
    parser.add_argument("--csv", default="playlist.csv", help="CSV that --dry-run writes (default: playlist.csv)")
    parser.add_argument("--overwrite", action="store_true", help="let --dry-run replace an existing CSV")
    parser.add_argument("--from-csv", metavar="CSV", help="download the links in this CSV instead of searching")
    parser.add_argument("--candidates", type=int, default=8,
                        help="search results to compare for each song (default: 8)")
    parser.add_argument("--loudness", type=float, default=-14.0,
                        help="target loudness in LUFS; closer to 0 is louder (default: -14)")
    parser.add_argument("--no-normalize", action="store_true", help="keep each song's original volume")
    parser.add_argument("--normalize-only", metavar="FOLDER",
                        help="don't download; just normalize the MP3s already in FOLDER")
    args = parser.parse_args()
    target = None if args.no_normalize else args.loudness

    if args.normalize_only:
        normalize_folder(args.normalize_only, args.bitrate, args.loudness)
        return

    if args.from_csv:
        rows = read_playlist_csv(args.from_csv)
        if not rows:
            sys.exit(f"No songs found in {args.from_csv}")
    else:
        songs = parse_song_list(args.song_list)
        if not songs:
            sys.exit(f"No songs found in {args.song_list}")
        if args.dry_run and Path(args.csv).exists() and not args.overwrite:
            sys.exit(f"{args.csv} already exists (it may have your edits). "
                     f"Use --overwrite to replace it, or --csv to pick another file name.")
        rows = search_songs(songs, args.candidates)
        if args.dry_run:
            write_playlist_csv(args.csv, rows)
            missing = sum(1 for r in rows if not r["url"])
            weak = [r["song"] for r in rows if r["status"] == "check: weak match"]
            print(f"\nSaved {len(rows)} songs to {args.csv} ({missing} without a link, "
                  f"{len(weak)} weak matches to check).")
            for song in weak:
                print(f"  check: {song}")
            print(f"Check the links, edit the url column, then run:\n"
                  f"    python download_songs.py --from-csv {args.csv}")
            return

    download_rows(rows, args.output, args.bitrate, target)

    # Write a summary so you can double-check which video was used for each song.
    report = Path(args.output) / "links.csv"
    write_playlist_csv(report, rows)
    failed = [r for r in rows if r["status"] not in ("downloaded", "skipped (exists)")]
    print(f"\nDone: {len(rows) - len(failed)}/{len(rows)} OK. Links saved to {report}")
    for row in failed:
        print(f"  {row['status']}: {row['song']}")

if __name__ == "__main__":
    main()

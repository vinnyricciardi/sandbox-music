#!/usr/bin/env python3
"""Search YouTube for each song in a list and save it as an MP3.

Usage:
    python download_songs.py                     # reads songs.txt, saves to ./music
    python download_songs.py my_list.txt -o out  # custom list / output folder
    python download_songs.py --dry-run           # only print the YouTube links found
    python download_songs.py --normalize-only music  # just even out volume of existing MP3s

Song list format (see songs.txt):
    1. Section Name          <- starts a section (saved as "01 - Section Name/")
    Title - Artist           <- one song per line
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
    """Return a list of (section_folder, song_query) tuples."""
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
        songs.append((section, line))
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


def find_video(ydl, query):
    """Return (title, url) of the top YouTube search result, or None."""
    info = ydl.extract_info(f"ytsearch1:{query} audio", download=False)
    entries = info.get("entries") or []
    if not entries:
        return None
    return entries[0].get("title"), entries[0].get("webpage_url") or entries[0].get("url")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("song_list", nargs="?", default="songs.txt", help="text file with one song per line")
    parser.add_argument("-o", "--output", default="music", help="folder to save MP3s into (default: music)")
    parser.add_argument("--bitrate", default="192", help="MP3 bitrate in kbps (default: 192)")
    parser.add_argument("--dry-run", action="store_true", help="only search and print links, don't download")
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

    songs = parse_song_list(args.song_list)
    if not songs:
        sys.exit(f"No songs found in {args.song_list}")

    search_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    results = []  # (query, youtube_title, url, status)

    with yt_dlp.YoutubeDL(search_opts) as searcher:
        for index, (section, query) in enumerate(songs, start=1):
            print(f"[{index}/{len(songs)}] {query}")
            try:
                found = find_video(searcher, query)
            except yt_dlp.utils.DownloadError as err:
                print(f"    search failed: {err}")
                results.append((query, "", "", "search failed"))
                continue
            if not found:
                print("    no results")
                results.append((query, "", "", "not found"))
                continue

            yt_title, url = found
            print(f"    -> {yt_title}\n       {url}")
            if args.dry_run:
                results.append((query, yt_title, url, "found"))
                continue

            folder = Path(args.output) / section
            folder.mkdir(parents=True, exist_ok=True)
            mp3_path = folder / f"{index:02d} - {safe_name(query)}.mp3"
            if mp3_path.exists():
                print("    already downloaded, skipping")
                results.append((query, yt_title, url, "skipped (exists)"))
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
                encode_mp3(source, mp3_path, args.bitrate, target, song_tags(query))
                print(f"    saved {mp3_path}")
                results.append((query, yt_title, url, "downloaded"))
            except yt_dlp.utils.DownloadError as err:
                print(f"    download failed: {err}")
                results.append((query, yt_title, url, "download failed"))
            except subprocess.CalledProcessError as err:
                print(f"    converting to MP3 failed: {(err.stderr or '').strip()[-300:]}")
                mp3_path.unlink(missing_ok=True)
                results.append((query, yt_title, url, "convert failed"))
            finally:
                if source:
                    source.unlink(missing_ok=True)

    # Write a summary so you can double-check which video was picked for each song.
    Path(args.output).mkdir(parents=True, exist_ok=True)
    report = Path(args.output) / "links.csv"

    with report.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["song", "youtube_title", "url", "status"])
        writer.writerows(results)

    failed = [r for r in results if "fail" in r[3] or r[3] == "not found"]
    print(f"\nDone: {len(results) - len(failed)}/{len(results)} OK. Links saved to {report}")
    for query, *_, status in failed:
        print(f"  {status}: {query}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Search YouTube for each song in a list and save it as an MP3.

Usage:
    python download_songs.py                     # reads songs.txt, saves to ./music
    python download_songs.py my_list.txt -o out  # custom list / output folder
    python download_songs.py --dry-run           # only print the YouTube links found

Song list format (see songs.txt):
    1. Section Name          <- starts a section (saved as "01 - Section Name/")
    Title - Artist           <- one song per line
    # comment                <- ignored

Requires: pip install yt-dlp   and   ffmpeg on your PATH.
"""

import argparse
import csv
import re
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
    args = parser.parse_args()

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

            download_opts = {
                "format": "bestaudio/best",
                # yt-dlp adds the .mp3 extension after conversion
                "outtmpl": str(mp3_path.with_suffix("")) + ".%(ext)s",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": args.bitrate},
                    {"key": "FFmpegMetadata"},
                ],
            }
            try:
                with yt_dlp.YoutubeDL(download_opts) as downloader:
                    downloader.download([url])
                print(f"    saved {mp3_path}")
                results.append((query, yt_title, url, "downloaded"))
            except yt_dlp.utils.DownloadError as err:
                print(f"    download failed: {err}")
                results.append((query, yt_title, url, "download failed"))

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

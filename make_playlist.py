#!/usr/bin/env python3
"""Turn playlist.csv into a YouTube playlist, in the same order as the CSV.

Two ways:

  Quick, no setup (unofficial YouTube link, may stop working at any time):
      python make_playlist.py playlist.csv --open
  Prints (and with --open, opens) links that play your songs as a temporary
  playlist, up to 50 songs per link. If YouTube shows fewer songs than that,
  use smaller links: --per-link 20

  A real playlist saved in your YouTube account (official YouTube Data API):
      python make_playlist.py playlist.csv --create "Birthday Party"
      python make_playlist.py playlist.csv --playlist-id PLxxxx   # add to an existing one
  Needs a one-time setup; see "Making a YouTube playlist" in README.md.
  Re-running with --playlist-id skips songs already in the playlist.

Only rows with a url are used.
"""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from download_songs import read_playlist_csv, video_id

WATCH_VIDEOS_LIMIT = 50  # YouTube's limit for watch_videos links (some reports say 20)
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def songs_with_ids(csv_path):
    songs = []
    for row in read_playlist_csv(csv_path):
        vid = video_id(row["url"])
        if vid:
            songs.append((row["song"], vid))
        elif row["url"]:
            print(f"Skipping {row['song']}: not a YouTube video link ({row['url']})")
    return songs


def quick_links(songs, open_browser, per_link=WATCH_VIDEOS_LIMIT):
    ids = [vid for _, vid in songs]
    chunks = [ids[i:i + per_link] for i in range(0, len(ids), per_link)]
    for n, chunk in enumerate(chunks, start=1):
        url = "https://www.youtube.com/watch_videos?video_ids=" + ",".join(chunk)
        print(f"\nPart {n} of {len(chunks)} ({len(chunk)} songs):\n{url}")
        if open_browser:
            webbrowser.open(url)
    print("\nThese are temporary playlists. To try keeping one, sign in, open it, and look for "
          "Save in the playlist panel;\nif there isn't one, change www.youtube.com to "
          "music.youtube.com and look for Save there.\nFor a real playlist in your account, "
          "use --create instead (see README).")


SIGN_IN_TIPS = """Opening your browser to sign in to Google...
  - Sign in with the Google account you added under "Test users" in Google Cloud.
  - "Google hasn't verified this app" is expected: click Continue.
  - "Access blocked ... Error 403: access_denied" means that account isn't a test user
    yet. See "Access blocked" in README.md.
"""


def check_client_secrets(secrets_file):
    """Catch the wrong kind of OAuth client, which Google rejects as "Access blocked"."""
    try:
        data = json.loads(Path(secrets_file).read_text())
    except (OSError, ValueError):
        sys.exit(f"{secrets_file} isn't a valid OAuth client file. Download it again from "
                 f"Google Cloud (Credentials > your OAuth client > Download JSON).")
    if "installed" not in data:
        kind = next(iter(data), "unknown")
        sys.exit(f"{secrets_file} is a '{kind}' OAuth client, but this script needs a 'Desktop app' "
                 f"client.\nGoogle blocks sign-in with the wrong type (Error 400: redirect_uri_mismatch).\n"
                 f"In Google Cloud go to Credentials > Create credentials > OAuth client ID > "
                 f"Application type: Desktop app,\nthen download its JSON and save it as {secrets_file}.")


def youtube_client(secrets_file, token_file):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Missing Google libraries. Run: pip install -r requirements-playlist.txt")

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not Path(secrets_file).exists():
            sys.exit(f"{secrets_file} not found. See 'Making a YouTube playlist' in README.md "
                     f"for how to download it from Google Cloud.")
        check_client_secrets(secrets_file)
        # Opens your browser so you can sign in and allow access to your YouTube account.
        print(SIGN_IN_TIPS)
        creds = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES).run_local_server(port=0)
        Path(token_file).write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def existing_video_ids(youtube, playlist_id):
    ids, page = set(), None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=playlist_id, maxResults=50, pageToken=page
        ).execute()
        ids.update(item["contentDetails"]["videoId"] for item in resp.get("items", []))
        page = resp.get("nextPageToken")
        if not page:
            return ids


def api_playlist(songs, args):
    from googleapiclient.errors import HttpError

    youtube = youtube_client(args.client_secrets, args.token)
    if args.playlist_id:
        playlist_id = args.playlist_id
        already = existing_video_ids(youtube, playlist_id)
    else:
        resp = youtube.playlists().insert(part="snippet,status", body={
            "snippet": {"title": args.create, "description": "Made with make_playlist.py"},
            "status": {"privacyStatus": args.privacy},
        }).execute()
        playlist_id, already = resp["id"], set()
        print(f"Created playlist '{args.create}' ({args.privacy})")

    added, failed = 0, []
    for n, (song, vid) in enumerate(songs, start=1):
        if vid in already:
            print(f"[{n}/{len(songs)}] {song}: already in playlist")
            continue
        try:
            youtube.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": vid},
            }}).execute()
            already.add(vid)
            added += 1
            print(f"[{n}/{len(songs)}] {song}: added")
        except HttpError as err:
            reason = err.reason if hasattr(err, "reason") else str(err)
            if err.resp.status == 403 and "quota" in str(err).lower():
                print(f"\nYouTube's daily API quota is used up after {added} songs. Run this tomorrow "
                      f"to add the rest:\n    python make_playlist.py {args.csv} --playlist-id {playlist_id}")
                break
            print(f"[{n}/{len(songs)}] {song}: failed ({reason})")
            failed.append(song)

    print(f"\nAdded {added} songs: https://www.youtube.com/playlist?list={playlist_id}")
    if failed:
        print(f"{len(failed)} failed (video may be private, removed or not embeddable):")
        for song in failed:
            print(f"  {song}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="?", default="playlist.csv", help="CSV with song and url columns")
    parser.add_argument("--open", action="store_true", help="open the quick playlist links in your browser")
    parser.add_argument("--per-link", type=int, default=WATCH_VIDEOS_LIMIT, metavar="N",
                        help=f"songs per quick link (default: {WATCH_VIDEOS_LIMIT}; try 20 if lists come up short)")
    parser.add_argument("--create", metavar="TITLE", help="create a real playlist with this title (YouTube API)")
    parser.add_argument("--playlist-id", help="add to this existing playlist instead (YouTube API)")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private",
                        help="privacy of a new playlist (default: private)")
    parser.add_argument("--client-secrets", default="client_secret.json",
                        help="OAuth client file from Google Cloud (default: client_secret.json)")
    parser.add_argument("--token", default="youtube_token.json",
                        help="where to remember your login (default: youtube_token.json)")
    args = parser.parse_args()

    songs = songs_with_ids(args.csv)
    if not songs:
        sys.exit(f"No YouTube links found in {args.csv}")
    print(f"{len(songs)} songs from {args.csv}")

    if args.create or args.playlist_id:
        api_playlist(songs, args)
    else:
        quick_links(songs, args.open, max(1, min(args.per_link, WATCH_VIDEOS_LIMIT)))


if __name__ == "__main__":
    main()

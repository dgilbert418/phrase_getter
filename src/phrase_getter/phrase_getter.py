#!/usr/bin/env python3

import os
import re
import argparse
import json
import datetime as dt

import pandas as pd
from yt_dlp import YoutubeDL
import ffmpeg
from pytube import YouTube
import requests
from dotenv import load_dotenv

import vtt_tools as vtt
import visemes

import traceback
import sys

load_dotenv()


def stamp_to_dt(stamp):
    return dt.datetime.strptime(stamp, "%H:%M:%S.%f")


def dt_to_stamp(date):
    return dt.datetime.strftime(date, "%H:%M:%S.%f")


def make_config(args):
    # Handle both argparse.Namespace and dict inputs
    if isinstance(args, dict):
        config = args.copy()
    else:
        config = {key: value for key, value in vars(args).items()}

    channel_root = f"{config['output_directory']}{config['channel_name']}/"

    config["paths"] = {
        "root": channel_root,
        "catalog": channel_root + "catalog.json",
        "video_dates": channel_root + "video_dates.json",
        "clips": channel_root + "clips/" + norm_txt(config["phrase"] + "/"),
        "full_videos": channel_root + "full_videos/",
        "manifest": channel_root + "manifests/" + norm_txt(config["phrase"]) + ".csv",
        "manifest_root": channel_root + "manifests/",
        "transcripts": {
            "vtt": channel_root + "transcripts/",
            "tsv": channel_root + "transcripts_tsv/",
            "vis": channel_root + "transcripts_vis/"
        }
    }

    if config["viseme_equivalent"]:
        config["phrase_vis"] = visemes.txt_to_viseme(norm_txt(config["phrase"]))
        config["paths"]["clips"] = channel_root + "clips/" + norm_txt(config["phrase"]) + "_vis/"
        config["paths"]["manifest"] = channel_root + "manifests/" + norm_txt(config["phrase"]) + "_vis.csv"

    config["overwrite"] = {
        'manifest': not config["skip_manifest"],
        'vtt': False,
        'tsv': False,
        'vis': False,
        'full_videos': False,
    }

    config["constants"] = {
        "DEFAULT_SLEEP_INTERVAL": 1.0  # for youtube-dl API calls
    }

    return config


def norm_pth(path):
    if not path[-1] == "/":
        path += "/"

    return path


def norm_txt(text):

    # Remove non-alphanumeric characters using regex
    normalized_text = re.sub(r'[^a-zA-Z0-9\s]', '', text)

    # Convert the text to lowercase
    normalized_text = normalized_text.lower()

    # strip
    normalized_text = normalized_text.strip()

    return normalized_text


def get_existing_video_ids(config):
    """Get video IDs from existing VTT transcript files."""
    vtt_dir = config["paths"]["transcripts"]["vtt"]
    if not os.path.exists(vtt_dir):
        return set()
    
    existing_ids = set()
    for filename in os.listdir(vtt_dir):
        if filename.endswith(".en.vtt"):
            # Extract video ID from filename format: {id}---{title}.en.vtt
            # Video IDs are 11 chars but can contain - and _, so match up to ---
            match = re.match(r'^(.+?)---', filename)
            if match:
                existing_ids.add(match.group(1))
    return existing_ids


def fetch_video_dates_batch(video_ids):
    """
    Fetch publish dates for multiple video IDs using YouTube Data API v3.
    Returns dict mapping video_id -> publish_date (as ISO string).
    """
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("Warning: YOUTUBE_API_KEY not found in environment. Cannot fetch video dates.")
        return {}
    
    video_dates = {}
    # YouTube API allows up to 50 IDs per request
    batch_size = 50
    
    for i in range(0, len(video_ids), batch_size):
        batch = video_ids[i:i + batch_size]
        ids_str = ",".join(batch)
        
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet",
            "id": ids_str,
            "key": api_key
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            if response.status_code != 200:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                print(f"YouTube API error ({response.status_code}): {error_msg}")
                continue
            
            for item in data.get("items", []):
                video_id = item["id"]
                published_at = item["snippet"]["publishedAt"]
                # Store as ISO string for JSON serialization
                video_dates[video_id] = published_at
                
        except Exception as e:
            print(f"Error fetching video dates for batch: {e}")
    
    return video_dates


def load_video_dates_cache(config):
    """Load cached video dates from file."""
    if os.path.exists(config["paths"]["video_dates"]):
        with open(config["paths"]["video_dates"]) as f:
            return json.load(f)
    return {}


def save_video_dates_cache(config, video_dates):
    """Save video dates to cache file."""
    with open(config["paths"]["video_dates"], "w") as f:
        json.dump(video_dates, f, indent=2)


def get_video_dates(config, video_ids):
    """
    Get publish dates for video IDs, using cache when available.
    Fetches missing dates from YouTube API and updates cache.
    """
    cached_dates = load_video_dates_cache(config)
    
    # Find IDs not in cache
    missing_ids = [vid for vid in video_ids if vid not in cached_dates]
    
    if missing_ids:
        print(f"Fetching dates for {len(missing_ids)} videos from YouTube API...")
        new_dates = fetch_video_dates_batch(missing_ids)
        cached_dates.update(new_dates)
        save_video_dates_cache(config, cached_dates)
        print(f"Cached {len(new_dates)} new video dates.")
    
    return cached_dates


def parse_date_arg(date_str):
    """Parse a date string in YYYY-MM-DD format to datetime."""
    if date_str is None:
        return None
    return dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)


def filter_videos_by_date(video_ids, video_dates, start_date, end_date):
    """Filter video IDs by publish date range."""
    filtered = []
    for vid in video_ids:
        if vid not in video_dates:
            continue
        
        # Parse ISO date string
        pub_date = dt.datetime.fromisoformat(video_dates[vid].replace("Z", "+00:00"))
        
        if start_date and pub_date < start_date:
            continue
        if end_date and pub_date > end_date:
            continue
        
        filtered.append(vid)
    
    return filtered


def get_catalog(config, force_refresh=False):

    channel_url = "https://www.youtube.com/c/" + config["channel_name"]
    alt_channel_url = "https://www.youtube.com/" + config["channel_name"]

    if not os.path.exists(config["paths"]["root"]):
        os.makedirs(config["paths"]["root"])

    # Skip if catalog exists unless force refresh requested
    if os.path.exists(config["paths"]["catalog"]) and not force_refresh:
        print(f"Using existing catalog. Use --force-catalog to refresh.")
        return

    ydl_opts = {
        'skip_download': True,
        'extract_flat': True
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url)
    except:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(alt_channel_url)

    with open(config["paths"]["catalog"], "w+") as f:
        json.dump(info, f)



def get_subtitles(video_id, config):
    video_url = "https://www.youtube.com/watch?v=" + video_id

    if not os.path.exists(config["paths"]["transcripts"]["vtt"]):
        os.makedirs(config["paths"]["transcripts"]["vtt"])

    output_path = config["paths"]["transcripts"]["vtt"] + "%(id)s---%(title)s.%(ext)s"

    ydl_opts = {
        'skip_download': True,
        'writesubs': True,
        'writeautomaticsub': True,
        'outtmpl': output_path,
        'overwrites': config['overwrite']['vtt']
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download(video_url)
    except Exception as e:
        print("Could not get subtitles for video:")
        print(video_url)


def get_all_subtitles(config, incremental=True):
    with open(config["paths"]["catalog"]) as f:
        catalog = json.load(f)

    # Get existing video IDs for incremental mode
    existing_ids = get_existing_video_ids(config) if incremental else set()
    if incremental and existing_ids:
        print(f"Found {len(existing_ids)} existing transcripts. Will only download new ones.")

    # Collect all video entries from catalog
    all_entries = []
    for tier_1_entry in catalog['entries']:
        if tier_1_entry["_type"] == "playlist":
            for tier_2_entry in tier_1_entry['entries']:
                all_entries.append(tier_2_entry)
        elif tier_1_entry["_type"] == "url":
            all_entries.append(tier_1_entry)

    # Filter to only new videos if incremental
    if incremental:
        new_entries = [e for e in all_entries if e['id'] not in existing_ids]
        print(f"Found {len(new_entries)} new videos to download transcripts for.")
    else:
        new_entries = all_entries

    # Download transcripts for new entries
    for entry in new_entries:
        try:
            get_subtitles(entry['id'], config)
        except:
            print(f"Could not get subtitles for {entry}")


def convert_all_subs_to_tsv(config):
    input_files = [f for f in os.listdir(config["paths"]["transcripts"]["vtt"]) if f.endswith(".en.vtt")]

    if not os.path.exists(config["paths"]["transcripts"]["tsv"]):
        os.makedirs(config["paths"]["transcripts"]["tsv"])

    for f in input_files:
        f_name = re.match(r'^(.*)\.en\.vtt$', f).group(1)
        f_out = f_name + ".tsv"
        if config['overwrite']['tsv'] or not os.path.exists(config["paths"]["transcripts"]["tsv"] + f_out):
            vtt.convert_to_tsv(config["paths"]["transcripts"]["vtt"] + f, config["paths"]["transcripts"]["tsv"] + f_out)


def download_video(video_id, config):
    video_url = "https://www.youtube.com/watch?v=" + video_id

    if not os.path.exists(config["paths"]["full_videos"]):
        os.makedirs(config["paths"]["full_videos"])

    output_path = config["paths"]["full_videos"] + "%(id)s---%(title)s.%(ext)s"

    ydl_opts = {
        'outtmpl': output_path,
        'overwrites': config['overwrite']['full_videos']
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download(video_url)


def get_instances(filename, config):
    if config["viseme_equivalent"]:
        transcript_dir = config["paths"]["transcripts"]["vis"]
        phrase = config["phrase_vis"]
    else:
        transcript_dir = config["paths"]["transcripts"]["tsv"]
        phrase = norm_txt(config["phrase"])

    matching_files = [f for f in os.listdir(transcript_dir) if f.startswith(filename)]
    filename_with_ext = matching_files[0]

    try:
        transcript = pd.read_csv(
            transcript_dir + filename_with_ext, sep="\t",
            keep_default_na=False,
            on_bad_lines='skip',
            quoting=3  # QUOTE_NONE - ignore quote characters
        )
    except Exception as e:
        print(f"Warning: Could not parse {filename_with_ext}: {e}")
        return []

    timestamps = []

    phrase_words = phrase.split(" ")
    for i in range(len(transcript)):
        cur_phrase = ""
        cur_line_u = i
        cur_text = transcript.loc[i, "text"]
        if not config["viseme_equivalent"]:
            cur_text = norm_txt(cur_text)

        for j, word in enumerate(phrase_words):
            if j > 0:
                cur_phrase += " "
            cur_phrase += word
            if cur_phrase in cur_text:
                if cur_phrase == phrase:
                    timestamps.append(transcript.loc[i, "start"])
                elif cur_text.endswith(cur_phrase):
                    while cur_text.endswith(cur_phrase) and (cur_line_u < (len(transcript)-1)):
                        cur_line_u += 1
                        next_word = transcript.loc[cur_line_u, "text"]
                        if not config["viseme_equivalent"]:
                            next_word = norm_txt(next_word)
                        cur_text = cur_text + " " + next_word
            else:
                break

    return timestamps


def make_manifest(config):
    if config['overwrite']['manifest'] or not os.path.exists(config["paths"]["manifest"]):
        manifest = pd.DataFrame({
            "video_id": [],
            "title": [],
            "phrase": [],
            "timestamp": [],
            "publish_date": []
        })
        num_videos = 0

        if config["viseme_equivalent"]:
            transcript_dir = config["paths"]["transcripts"]["vis"]
            phrase = visemes.txt_to_viseme(norm_txt(config["phrase"]))
        else:
            transcript_dir = config["paths"]["transcripts"]["tsv"]
            phrase = norm_txt(config["phrase"])

        print(f"Making manifest for phrase \"{config['phrase']}\"...")

        # Get all transcript files and extract video info
        all_files = []
        for path in os.listdir(transcript_dir):
            filename = path.replace(".tsv", "")
            components = re.search(r'(.*)---(.*)', filename)
            if components:
                all_files.append({
                    'filename': filename,
                    'video_id': components.group(1),
                    'title': components.group(2)
                })

        # Apply date filtering if specified, or fetch dates for timestamp overlay
        start_date = parse_date_arg(config.get("start_date"))
        end_date = parse_date_arg(config.get("end_date"))
        need_dates = start_date or end_date or config.get("timestamp_videos", False)
        
        if need_dates:
            video_ids = [f['video_id'] for f in all_files]
            video_dates = get_video_dates(config, video_ids)
            
            if start_date or end_date:
                filtered_ids = set(filter_videos_by_date(video_ids, video_dates, start_date, end_date))
                all_files = [f for f in all_files if f['video_id'] in filtered_ids]
                print(f"After date filtering: {len(all_files)} videos in range.")
        else:
            video_dates = {}

        for file_info in all_files:
            filename = file_info['filename']
            video_id = file_info['video_id']
            title = file_info['title']

            instances = get_instances(filename, config)
            if len(instances) > 0:
                num_videos += 1
                pub_date = video_dates.get(video_id, "")
                for instance in instances:
                    manifest = pd.concat([
                        manifest,
                        pd.DataFrame([
                            {
                                "video_id": video_id,
                                "title": title,
                                "phrase": phrase,
                                "timestamp": instance,
                                "publish_date": pub_date
                            }
                        ])
                    ], ignore_index=True)

        print(f"Found {len(manifest)} clips in {num_videos} videos.")
        print(f"Writing manifest to " + config["paths"]["manifest"])

        if not os.path.exists(config["paths"]["manifest_root"]):
            os.makedirs(config["paths"]["manifest_root"])
        manifest.to_csv(config["paths"]["manifest"], header=True, index=False)


def clip_all(config):
    if config["overwrite"]["manifest"] or (not os.path.exists(f"{config['paths']['manifest']}{config['phrase']}.csv")):
        make_manifest(config)

    manifest = pd.read_csv(config["paths"]["manifest"])

    if config["max_files"] and (config["max_files"] < len(manifest)):
        num_clips = config["max_files"]
    else:
        num_clips = len(manifest)

    print(f"Creating {num_clips} clips...")
    for i in range(num_clips):
        try:
            print(f"[{i+1}/{num_clips}] {manifest.loc[i, 'video_id']} - {manifest.loc[i, 'title'][:50]}...")
            make_clip(
                timestamp=manifest.loc[i, "timestamp"],
                video_id=manifest.loc[i, "video_id"],
                title=manifest.loc[i, "title"],
                publish_date=manifest.loc[i, "publish_date"] if "publish_date" in manifest.columns else None,
                config=config
            )
        except Exception as e:
            print(f"Could not download manifest entry {i} (video_id {manifest.loc[i, 'video_id']})")
            print(f"Exception: {str(e)}")


def format_date_ordinal(date_str):
    """Format date string to 'January 24th, 2026' format."""
    if not date_str:
        return None
    try:
        date = dt.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        day = date.day
        if 11 <= day <= 13:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        return date.strftime(f"%B {day}{suffix}, %Y")
    except:
        return None


def make_clip(timestamp, video_id, title, config, publish_date=None):

    timestamp_dt = stamp_to_dt(timestamp)

    start_dt = timestamp_dt - dt.timedelta(seconds=config["seconds_before"])
    end_dt = timestamp_dt + dt.timedelta(seconds=config["seconds_after"])

    diff_seconds = (end_dt - start_dt).total_seconds()

    output_path = f"{config['paths']['clips']}/{video_id}---{title}---{start_dt.strftime('%H%M%S')}---{end_dt.strftime('%H%M%S')}.mp4"

    if not os.path.exists(config['paths']['clips']):
        os.makedirs(config['paths']['clips'])

    # Skip if clip already exists (unless force_clips is set)
    if os.path.exists(output_path) and not config.get("force_clips", False):
        return

    if not os.path.exists(config['paths']['full_videos']):
        os.makedirs(config['paths']['full_videos'])

    matching_input_files = [f for f in os.listdir(config['paths']['full_videos']) if f.startswith(video_id)]
    if len(matching_input_files) == 0:
        download_video(video_id, config)
        matching_input_files = [f for f in os.listdir(config['paths']['full_videos']) if f.startswith(video_id)]

    if len(matching_input_files) > 0:
        input_path = f"{config['paths']['full_videos'] + matching_input_files[0]}"

        input_stream = ffmpeg.input(input_path, ss=dt_to_stamp(start_dt), t=diff_seconds)
        
        # Add timestamp overlay if requested
        if config.get("timestamp_videos", False) and publish_date:
            formatted_date = format_date_ordinal(publish_date)
            if formatted_date:
                # Build ffmpeg command directly for proper font handling on Windows
                import subprocess
                font_file = "C:/Windows/Fonts/pala.ttf"  # Palatino Linotype - elegant serif
                drawtext_filter = (
                    f"drawtext=text='{formatted_date}'"
                    f":fontfile='{font_file}'"
                    f":fontsize=156"
                    f":fontcolor=white"
                    f":borderw=4"
                    f":bordercolor=black"
                    f":shadowcolor=black@0.6"
                    f":shadowx=4"
                    f":shadowy=4"
                    f":x=w-tw-50"
                    f":y=40"
                )
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', dt_to_stamp(start_dt),
                    '-i', input_path,
                    '-t', str(diff_seconds),
                    '-vf', drawtext_filter,
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    output_path
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=int(diff_seconds) * 10 + 30)
                if result.returncode != 0:
                    stderr = result.stderr.decode() if result.stderr else ""
                    if "Error parsing OBU data" in stderr or "Invalid data found" in stderr:
                        print(f"Skipping clip due to corrupted video: {video_id}")
                        if os.path.exists(output_path):
                            os.remove(output_path)
                return
            else:
                process = (input_stream
                    .output(output_path, f='mp4', vcodec='libx264')
                    .overwrite_output()
                )
        else:
            process = (input_stream
                .output(output_path, f='mp4', vcodec='libx264')
                .overwrite_output()
            )

        # Timeout: clip duration * 10 (for slow encodes) + 30 seconds buffer
        timeout_seconds = int(diff_seconds) * 10 + 30
        
        try:
            import subprocess
            cmd = process.compile()
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                timeout=timeout_seconds
            )
            if result.returncode != 0:
                stderr = result.stderr.decode() if result.stderr else ""
                if "Error parsing OBU data" in stderr or "Invalid data found" in stderr:
                    print(f"Skipping clip due to corrupted video: {video_id}")
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    return
        except subprocess.TimeoutExpired:
            print(f"Timeout encoding clip from {video_id} - skipping (likely corrupted)")
            if os.path.exists(output_path):
                os.remove(output_path)
            return
    else:
        print("No matching input files!")


def get_video_release_date(video_id):
    url = f'https://www.youtube.com/watch?v={video_id}'
    try:
        yt = YouTube(url)
        release_date = yt.publish_date
        return release_date
    except Exception as e:
        print(f"Error: {e}")
        return None


def download_channel_subs(config):
    get_catalog(config)
    get_all_subtitles(config)
    convert_all_subs_to_tsv(config)


def make_vis_tsvs(config):
    input_files = [f for f in os.listdir(config['paths']['transcripts']['tsv']) if f.endswith(".tsv")]

    if not os.path.exists(config['paths']['transcripts']['vis']):
        os.makedirs(config['paths']['transcripts']['vis'])

    for f in input_files:
        f_name = re.match(r'^(.*)\.tsv$', f).group(1)
        f_out = f_name + ".tsv"
        transcript = pd.read_csv(config['paths']['transcripts']['tsv'] + f, sep="\t")
        transcript["text"] = transcript["text"].apply(visemes.txt_to_viseme)
        transcript.to_csv(config['paths']['transcripts']['vis'] + f_out, sep="\t", header=True, index=False)


def run(config):
    if config["download_subs"] or ((not config["skip_manifest"]) and (not os.path.exists(config["paths"]["transcripts"]["tsv"]))):
        print("Transcripts do not exist. Downloading channel subs...")
        download_channel_subs(config)

    if config["viseme_equivalent"] and (not os.path.exists(config["paths"]["transcripts"]["vis"])):
        make_vis_tsvs(config)

    if config["skip_download"]:
        make_manifest(config)
    else:
        clip_all(config)

def get(
    phrase, channel_name, output_directory=os.getcwd(), skip_download=False, max_files=None,
    seconds_before=1, seconds_after=5, skip_manifest=False, download_subs=False, viseme_equivalent=False,
    start_date=None, end_date=None, force_clips=False, timestamp_videos=False
):
    args = {
        'phrase': phrase,
        'channel_name': channel_name,
        'output_directory': output_directory,
        'skip_download': skip_download,
        'max_files': max_files,
        'seconds_before': seconds_before,
        'seconds_after': seconds_after,
        'skip_manifest': skip_manifest,
        'download_subs': download_subs,
        'viseme_equivalent': viseme_equivalent,
        'start_date': start_date,
        'end_date': end_date,
        'force_clips': force_clips,
        'timestamp_videos': timestamp_videos
    }
    run(make_config(args))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Get clips of all instances of a phrase from a youtube channel's history."
    )

    parser.add_argument("phrase", type=str, help="Phrase to find clips of")
    parser.add_argument("channel_name", type=str, help="Youtube channel name")
    parser.add_argument(
        "--output_directory", "-o", type=str, default=os.getcwd(),
        help="Directory for outputting intermediate files, full downloaded videos and clips."
             "If unspecified, uses current working directory."
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Use this flag to only output a table of instances without downloading videos."
    )
    parser.add_argument("--max-files", type=int, help="Caps the number of clips outputted. Good for common phrases.")
    parser.add_argument("--seconds-before", type=int, default=1,
                        help="Number of seconds before phrase instance to start each clip")
    parser.add_argument("--seconds-after", type=int, default=5,
                        help="Number of seconds after phrase instance to end each clip")
    parser.add_argument(
        "--skip-manifest", action="store_true",
        help="Use this flag to skip manifest creation step if manifest already exists for that phrase."
    )
    parser.add_argument(
        "--download-subs", action="store_true",
        help="Use this flag to redownload all subtitles even if they already exist in the output directory."
    )
    parser.add_argument(
        "--viseme-equivalent", action="store_true",
        help="Use this flag to search for clips which are lip-reading equivalent to the provided phrase."
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="Only include videos published on or after this date (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="Only include videos published on or before this date (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        "--force-clips", action="store_true",
        help="Force re-creation of clips even if they already exist."
    )
    parser.add_argument(
        "--timestamp-videos", action="store_true",
        help="Add publish date overlay (e.g., 'January 24th, 2026') to top-right of clips."
    )

    args = parser.parse_args()
    return args


if __name__ == '__main__':

    args = parse_args()
    config = make_config(args)
    run(config)

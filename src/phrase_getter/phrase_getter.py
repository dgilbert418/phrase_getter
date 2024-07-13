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

import vtt_tools as vtt
import visemes

import traceback
import sys


def stamp_to_dt(stamp):
    return dt.datetime.strptime(stamp, "%H:%M:%S.%f")


def dt_to_stamp(date):
    return dt.datetime.strftime(date, "%H:%M:%S.%f")


def make_config(args):
    config = {key: value for key, value in vars(args).items()}

    channel_root = f"{config['output_directory']}{config['channel_name']}/"

    config["paths"] = {
        "root": channel_root,
        "catalog": channel_root + "catalog.json",
        "clips": channel_root + "clips/" + norm_txt(config["phrase"] + "/"),
        "full_videos": channel_root + "full_videos/",
        "manifest": channel_root + "manifests/" + norm_txt(config["phrase"]) + ".csv",
        "manifest_root": channel_root + "manifests/",
        "transcripts": {
            "vtt": channel_root + "transcripts/vtt/",
            "tsv": channel_root + "transcripts/tsv/",
            "vis": channel_root + "transcripts/vis/"
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


def get_catalog(config):
    channel_url = "https://www.youtube.com/c/" + config["channel_name"]

    if not os.path.exists(config["paths"]["root"]):
        os.makedirs(config["paths"]["root"])

    ydl_opts = {
        'skip_download': True,
        'extract_flat': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url)

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


def get_all_subtitles(config):
    with open(config["paths"]["catalog"]) as f:
        catalog = json.load(f)

    def _download_transcript(entry):
        if config['overwrite']['vtt'] or not os.path.exists(f"{config['paths']['transcripts']['vtt']}{entry['id']}---{entry['title']}.en.vtt"):
            try:
                get_subtitles(entry['id'], config)
            except:
                print(f"Could not get subtitles for {entry}")
        else:
            print(f"Subtitles for {entry['id']}---{entry['title']} already exist.")

    for tier_1_entry in catalog['entries']:
        if tier_1_entry["_type"] == "playlist":
            for tier_2_entry in tier_1_entry['entries']:
                _download_transcript(tier_2_entry)
        elif tier_1_entry["_type"] == "url":
            _download_transcript(tier_1_entry)


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

    transcript = pd.read_csv(
        transcript_dir + filename_with_ext, sep="\t",
        keep_default_na=False
    )

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
            "timestamp": []
        })
        num_videos = 0

        if config["viseme_equivalent"]:
            transcript_dir = config["paths"]["transcripts"]["vis"]
            phrase = visemes.txt_to_viseme(norm_txt(config["phrase"]))
        else:
            transcript_dir = config["paths"]["transcripts"]["tsv"]
            phrase = norm_txt(config["phrase"])

        print(f"Making manifest for phrase \"{config['phrase']}\"...")


        for path in os.listdir(transcript_dir):
            filename= path.replace(".tsv", "")
            components = re.search(r'(.*)---(.*)', filename)
            video_id = components.group(1)
            title = components.group(2)

            instances = get_instances(filename, config)
            if len(instances) > 0:
                num_videos += 1
                for instance in instances:
                    manifest = manifest.append(
                        pd.DataFrame([
                            {
                                "video_id": video_id,
                                "title": title,
                                "phrase": phrase,
                                "timestamp": instance
                            }
                        ])
                    )

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

    for i in range(num_clips):
        try:
            make_clip(
                timestamp=manifest.loc[i, "timestamp"],
                video_id=manifest.loc[i, "video_id"],
                title=manifest.loc[i, "title"],
                config=config
            )
        except Exception as e:
            print(f"Could not download manifest entry {i} (video_id {manifest.loc[i, 'video_id']}")
            print(f"Exception: {str(e)}")


def make_clip(timestamp, video_id, title, config):

    timestamp_dt = stamp_to_dt(timestamp)

    start_dt = timestamp_dt - dt.timedelta(seconds=config["seconds_before"])
    end_dt = timestamp_dt + dt.timedelta(seconds=config["seconds_after"])

    diff_seconds = (end_dt - start_dt).total_seconds()

    output_path = f"{config['paths']['clips']}/{video_id}---{title}---{start_dt.strftime('%H%M%S')}---{end_dt.strftime('%H%M%S')}.mp4"

    if not os.path.exists(config['paths']['clips']):
        os.makedirs(config['paths']['clips'])

    if not os.path.exists(config['paths']['full_videos']):
        os.makedirs(config['paths']['full_videos'])

    matching_input_files = [f for f in os.listdir(config['paths']['full_videos']) if f.startswith(video_id)]
    if len(matching_input_files) == 0:
        download_video(video_id, config)
        matching_input_files = [f for f in os.listdir(config['paths']['full_videos']) if f.startswith(video_id)]

    if len(matching_input_files) > 0:
        input_path = f"{config['paths']['full_videos'] + matching_input_files[0]}"

        process = (ffmpeg
            .input(input_path, ss=dt_to_stamp(start_dt), t=diff_seconds)
            .output(output_path, f='mp4', vcodec='libx264')
            .overwrite_output()
        )

        process.run()
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
    seconds_before=1, seconds_after=5, skip_manifest=False, download_subs=False, viseme_equivalent=False
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
        'viseme_equivalent': viseme_equivalent
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

    args = parser.parse_args()
    return args


if __name__ == '__main__':

    args = parse_args()
    config = make_config(args)
    run(config)

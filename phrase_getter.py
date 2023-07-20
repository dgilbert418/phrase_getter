import os
import re
import datetime as dt
from yt_dlp import YoutubeDL
import ffmpeg
import json
import vtt_tools as vtt
import pandas as pd

DEFAULT_SLEEP_INTERVAL = 1.0 # for youtube-dl API calls

def norm_pth(path):
    if not path[-1] == "/":
        path += "/"

    return path

def norm_txt(text):
    # Remove non-alphanumeric characters using regex
    normalized_text = re.sub(r'[^a-zA-Z0-9\s]', '', text)

    # Convert the text to lowercase
    normalized_text = normalized_text.lower()

    return normalized_text


def get_catalog(channel_name, data_dir=os.getcwd()):
    channel_url = "https://www.youtube.com/c/" + channel_name
    output_dir = f"{norm_pth(data_dir)}/{channel_name}/"

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_file = f"{output_dir}catalog.json"

    ydl_opts = {
        'skip_download': True,
        'extract_flat': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url)

    with open(output_file, "w+") as f:
        json.dump(info, f)


def get_subtitles(video_id, channel_name, data_dir=os.getcwd(), overwrite=False):
    video_url = "https://www.youtube.com/watch?v=" + video_id
    transcripts_dir = f"{norm_pth(data_dir)}{channel_name}/transcripts/"
    if not os.path.exists(transcripts_dir):
        os.makedirs(transcripts_dir)

    output_path = transcripts_dir + "%(id)s---%(title)s.%(ext)s"

    ydl_opts = {
        'skip_download': True,
        'writesubs': True,
        'writeautomaticsub': True,
        'outtmpl': output_path,
        'overwrites': overwrite
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download(video_url)
    except Exception as e:
        print("Could not get subtitles for video:")
        print(video_url)


def get_all_subtitles(channel_name, data_dir=os.getcwd(), overwrite=False):
    catalog_path = f"{norm_pth(data_dir)}{channel_name}/catalog.json"
    with open(catalog_path) as f:
        catalog = json.load(f)

    for playlist in catalog['entries']:
        for entry in playlist['entries']:
            if overwrite or not os.path.exists(f"{norm_pth(data_dir)}{channel_name}/transcripts/{entry['id']}---{entry['title']}.en.vtt"):
                try:
                    get_subtitles(entry['id'], channel_name, data_dir, overwrite)
                except:
                    print(f"Could not get subtitles for {entry}")
            else:
                print(f"Subtitles for {entry['id']}---{entry['title']} already exist.")


def convert_all_subs_to_tsv(channel_name, data_dir=os.getcwd()):
    input_dir = f"{norm_pth(data_dir)}{channel_name}/transcripts/"
    output_dir = f"{norm_pth(data_dir)}{channel_name}/transcripts_tsv/"

    input_files = [f for f in os.listdir(input_dir) if f.endswith(".en.vtt")]

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for f in input_files:
        f_name = re.match(r'^(.*)\.en\.vtt$', f).group(1)
        f_out = f_name + ".tsv"
        vtt.convert_to_tsv(input_dir + f, output_dir + f_out)


def download_video(video_id, output_dir=os.getcwd(), overwrite=False):
    video_url = "https://www.youtube.com/watch?v=" + video_id
    output_dir = norm_pth(output_dir)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_path = output_dir + "%(id)s---%(title)s.%(ext)s"

    ydl_opts = {
        'outtmpl': output_path,
        'overwrites': overwrite
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download(video_url)


def get_instances(filename, phrase, transcript_dir):
    phrase = norm_txt(phrase)
    transcript_dir = norm_pth(transcript_dir)

    matching_files = [f for f in os.listdir(transcript_dir) if f.startswith(filename)]
    filename_with_ext = matching_files[0]

    transcript = pd.read_csv(transcript_dir + filename_with_ext, sep="\t")

    timestamps = []

    phrase_words = phrase.split(" ")
    for i in range(len(transcript)):
        cur_phrase = ""
        cur_line_u = i
        cur_text = norm_txt(transcript.loc[i, "text"])
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
                        cur_text = cur_text + " " + norm_txt(transcript.loc[cur_line_u, "text"])
            else:
                break

    return timestamps


def make_manifest(phrase, channel_name, data_dir):
    transcript_tsv_dir = f"{norm_pth(data_dir)}{channel_name}/transcripts_tsv/"
    manifest_dir = f"{norm_pth(data_dir)}{channel_name}/manifests/"

    manifest = pd.DataFrame({
        "video_id": [],
        "title": [],
        "phrase": [],
        "timestamp": []
    })
    num_videos = 0

    print(f"Making manifest for phrase \"{phrase}\"...")

    for path in os.listdir(transcript_tsv_dir):
        filename= path.replace(".tsv", "")
        components = re.search(r'(.*)---(.*)', filename)
        video_id = components.group(1)
        title = components.group(2)


        instances = get_instances(filename, phrase, transcript_tsv_dir)
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

            if not os.path.exists(manifest_dir):
                os.makedirs(manifest_dir)

    print(f"Found {len(manifest)} clips in {num_videos} videos.")
    print(f"Writing manifest to " + manifest_dir + norm_txt(phrase) + ".csv")

    manifest.to_csv(manifest_dir + norm_txt(phrase) + ".csv", header=True, index=False)


def clip_all(phrase, channel_name, data_dir, max_files=None, seconds_before=3, seconds_after=5, overwrite_manifest=False):

    manifest_path = f"{data_dir}{channel_name}/manifests/{norm_txt(phrase)}.csv"
    if overwrite_manifest or (not os.path.exists(manifest_path)):
        make_manifest(phrase, channel_name, data_dir)

    manifest = pd.read_csv(manifest_path)

    data_dir = norm_pth(data_dir)

    if max_files and (max_files < len(manifest)):
        num_clips = max_files
    else:
        num_clips = len(manifest)

    for i in range(num_clips):
        try:
            make_clip(
                timestamp=manifest.loc[i, "timestamp"],
                video_id=manifest.loc[i, "video_id"],
                title=manifest.loc[i, "title"],
                channel_name=channel_name,
                data_dir=data_dir,
                seconds_before=seconds_before,
                seconds_after=seconds_after
            )
        except Exception as e:
            print(f"Could not download manifest entry {i} (video_id {manifest.loc[i, 'video_id']}")
            print(f"Exception: {str(e)}")


def stamp_to_dt(stamp):
    return dt.datetime.strptime(stamp, "%H:%M:%S.%f")

def dt_to_stamp(date):
    return dt.datetime.strftime(date, "%H:%M:%S.%f")


def make_clip(timestamp, video_id, title, channel_name, data_dir, seconds_before=3, seconds_after=5):

    timestamp_dt = stamp_to_dt(timestamp)

    start_dt = timestamp_dt - dt.timedelta(seconds=seconds_before)
    end_dt = timestamp_dt + dt.timedelta(seconds=seconds_after)

    diff_seconds = (end_dt - start_dt).total_seconds()

    full_videos_dir = f"{data_dir}{channel_name}/full_videos/"
    phrase_dir = f"{data_dir}{channel_name}/clips/{norm_txt(phrase)}"
    output_path = f"{phrase_dir}/{video_id}---{title}---{start_dt.strftime('%H%M%S')}---{end_dt.strftime('%H%M%S')}.mp4"

    if not os.path.exists(phrase_dir):
        os.makedirs(phrase_dir)

    if not os.path.exists(full_videos_dir):
        os.makedirs(full_videos_dir)

    matching_input_files = [f for f in os.listdir(full_videos_dir) if f.startswith(video_id)]
    if len(matching_input_files) == 0:
        download_video(video_id, full_videos_dir)
        matching_input_files = [f for f in os.listdir(full_videos_dir) if f.startswith(video_id)]

    if len(matching_input_files) > 0:
        input_path = f"{full_videos_dir + matching_input_files[0]}"

        process = (ffmpeg
            .input(input_path, ss=dt_to_stamp(start_dt), t=diff_seconds)
            .output(output_path, f='mp4', vcodec='libx264')
            .overwrite_output()
        )

        process.run()
    else:
        print("No matching input files!")


if __name__ == '__main__':

    directory = "H:/clips/"


    #channel_name = "LexFridman"
    channel_name = "BretWeinsteinDarkHorse"
    #channel_name = "Campbellteaching"
    #channel_name = "JordanPetersonVideos"
    #channel_name = "BenShapiro"

    phrase = "game theory"

    #get_catalog(channel_name, directory)
    #get_all_subtitles(channel_name, directory)
    #convert_all_subs_to_tsv(channel_name, directory)

    #make_manifest(phrase, channel_name, directory)
    clip_all(phrase, channel_name, directory)




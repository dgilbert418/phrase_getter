import os
import re
import datetime as dt
from yt_dlp import YoutubeDL
import ffmpeg
import json

DEFAULT_BUFFER_LINES = 20 # amount of transcript lines before and after the phrase to keep in clip
DEFAULT_OVERLAP_THRESHOLD = .3 # Between 0 and 1. 0 = Combine all overlapping clips; 1 = combine none
DEFAULT_SLEEP_INTERVAL = 1.0 # for youtube-dl API calls

def norm_pth(path):
    if not path[-1] == "/":
        path += "/"

    return path


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
        print(e)


def get_all_subtitles(channel_name, data_dir=os.getcwd(), overwrite=False):
    catalog_path = f"{norm_pth(data_dir)}{channel_name}/catalog.json"
    with open(catalog_path) as f:
        catalog = json.load(f)

    for entry in catalog['entries']:
        if overwrite or not os.path.exists(f"{norm_pth(data_dir)}channel_name/{entry['id']}---{entry['title']}.en.vtt"):
            get_subtitles(entry['id'], channel_name, data_dir, overwrite)
        else:
            print(f"Subtitles for {entry['id']}---{entry['title']} already exist.")


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


def get_instances(filename, phrase, transcript_dir, buffer_lines=DEFAULT_BUFFER_LINES):
    instances = []
    if not transcript_dir[-1] == "/":
        transcript_dir += "/"

    matching_files = [f for f in os.listdir(transcript_dir) if f.startswith(filename)]
    filename_with_ext = matching_files[0]

    with open(transcript_dir + filename_with_ext, 'r', encoding='utf-8', errors="ignore") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if phrase in line:
            instances.append("  ".join(lines[max(0, i - buffer_lines): i + buffer_lines + 1]))
    return instances


def get_time_bounds(instance):
    time_format = "\d\d:\d\d:\d\d\.\d\d\d"
    timestamps = re.findall(time_format, instance)
    return timestamps[0], timestamps[-1]


def clip_all_instances(phrase, channel_name, data_dir, buffer_lines = DEFAULT_BUFFER_LINES, max_files=None):
    file_count = 0
    if not data_dir[-1] == "/":
        data_dir += "/"
    for path in os.listdir(f"{data_dir}{channel_name}/transcripts/"):
        filename = path.replace(".en.vtt", "")
        clip_all_instances_in_file(filename, phrase, channel_name, data_dir, buffer_lines)
        file_count += 1
        if max_files and file_count >= max_files:
            break


def combine_overlapping_clips(time_bounds, overlap_threshold):
    i = 0
    while i < len(time_bounds) - 1:
        l_outer = min(time_bounds[i][0], time_bounds[i + 1][0])
        l_inner = max(time_bounds[i][0], time_bounds[i + 1][0])
        r_inner = min(time_bounds[i][1], time_bounds[i + 1][1])
        r_outer = max(time_bounds[i][1], time_bounds[i + 1][1])

        inner_seconds = (stamp_to_dt(r_inner) - stamp_to_dt(l_inner)).total_seconds()
        outer_seconds = (stamp_to_dt(r_outer) - stamp_to_dt(l_outer)).total_seconds()
        if inner_seconds / outer_seconds > overlap_threshold:
            time_bounds[i] = (l_outer, r_outer)
            del time_bounds[i + 1]
        else:
            i += 1
    return time_bounds


def clip_all_instances_in_file(
        filename, phrase, channel_name, data_dir,
        buffer_lines=DEFAULT_BUFFER_LINES, overlap_threshold=DEFAULT_OVERLAP_THRESHOLD
):

    transcript_dir = f"{data_dir}/{channel_name}/transcripts/"
    instances = get_instances(filename, phrase, transcript_dir, buffer_lines)
    time_bounds = [get_time_bounds(instance) for instance in instances]
    time_bounds = combine_overlapping_clips(time_bounds, overlap_threshold)

    for bound in time_bounds:
        make_clip(bound, filename, phrase, channel_name, data_dir)


def stamp_to_dt(stamp):
    return dt.datetime.strptime(stamp, "%H:%M:%S.%f")


def normalize_str(a_str):
    a_str = "".join([character for character in a_str if (character.isalnum() or character == " ")])
    a_str = a_str.strip()
    return a_str


def make_clip(time_bounds, filename, phrase, channel_name, data_dir):
    video_id, title = filename.split("---")

    start_time = stamp_to_dt(time_bounds[0])
    end_time = stamp_to_dt(time_bounds[1])
    diff_seconds = (end_time-start_time).total_seconds()

    full_videos_dir = f"{data_dir}{channel_name}/full_videos/"
    phrase_dir = f"{data_dir}{channel_name}/clips/{normalize_str(phrase)}"
    output_path = f"{phrase_dir}/{video_id}---{title}---{start_time.strftime('%H%M%S')}---{end_time.strftime('%H%M%S')}.mp4"

    if not os.path.exists(phrase_dir):
        os.makedirs(phrase_dir)

    if not os.path.exists(full_videos_dir):
        os.makedirs(full_videos_dir)

    matching_input_files = [f for f in os.listdir(full_videos_dir) if f.startswith(filename)]
    if len(matching_input_files) == 0:
        download_video(video_id, full_videos_dir)
        matching_input_files = [f for f in os.listdir(full_videos_dir) if f.startswith(filename)]

    input_path = f"{full_videos_dir + matching_input_files[0]}"

    process = (ffmpeg
        .input(input_path, ss=time_bounds[0], t=diff_seconds)
        .output(output_path, f='mp4', vcodec='libx264')
        .overwrite_output()
    )

    process.run()
    #cmd_str = f"ffmpeg -ss {time_bounds[0]} -i \"{input_path}\" -c copy -t {diff_seconds} \"{output_path}\""
    #cmd_str = f"ffmpeg -ss {time_bounds[0]} -i \"{input_path}\" -vcodec libx264 -t {diff_seconds} \"{output_path}\""
    #os.system(cmd_str)


if __name__ == '__main__':
    directory = "H:/clips/"
    channel_name = "BretWeinsteinDarkHorse"
    phrase = "lockdown"
    buffer_lines = 45

    #get_catalog(channel_name, directory)
    #get_all_subtitles(channel_name, directory)
    clip_all_instances(phrase, channel_name, directory, buffer_lines)
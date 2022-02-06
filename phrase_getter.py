import os
import re
import datetime as dt

DEFAULT_BUFFER_LINES = 20 # amount of transcript lines before and after the phrase to keep in clip
DEFAULT_OVERLAP_THRESHOLD = .3 # Between 0 and 1. 0 = Combine all overlapping clips; 1 = combine none
DEFAULT_SLEEP_INTERVAL = 1.0 # for youtube-dl API calls

def get_subtitles(channel_name, data_dir = os.getcwd(), sleep_interval = DEFAULT_SLEEP_INTERVAL):

    channel_url = "https://www.youtube.com/c/" + channel_name
    print(f"Writing transcripts to {data_dir}.")

    transcripts_dir = f"{data_dir}/{channel_name}/transcripts/"
    if not os.path.exists(transcripts_dir):
        os.makedirs(transcripts_dir)

    output_path = transcripts_dir + "%(id)s---%(title)s.%(ext)"
    os.system(f"youtube-dl --write-auto-sub --convert-subs=srt --skip-download {channel_url} -o {output_path} --ignore-errors --sleep-interval {sleep_interval}")

def list_videos(channel_url):
    cmd_str = f"youtube-dl --get-filename {channel_url} -o '%(upload_date)s---%(title)s---https://www.youtube.com/watch?v=%(id)s'"
    print(cmd_str)
    os.system(cmd_str)

def download_video(video_id, output_dir = os.getcwd()):
    if not output_dir[-1] == "/":
        output_dir += "/"

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_path = output_dir + "%(id)s---%(title)s.%(ext)s"
    cmd_str = f"yt-dlp https://www.youtube.com/watch?v={video_id} -f 22 -o {output_path}"
    os.system(cmd_str)

def get_instances(filename, phrase, transcript_dir, buffer_lines=DEFAULT_BUFFER_LINES):
    instances = []
    if not transcript_dir[-1] == "/":
        transcript_dir += "/"
    with open(transcript_dir + f"{filename}.en.vtt", 'r') as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if phrase in line:
            instances.append("  ".join(lines[max(0, i - buffer_lines): i + buffer_lines + 1]))
    return instances

def get_time_bounds(instance):
    time_format = "\d\d:\d\d:\d\d\.\d\d\d"
    timestamps = re.findall(time_format, instance)
    return timestamps[0], timestamps[-1]

def clip_all_instances(phrase, channel_name, data_dir, buffer_lines = DEFAULT_BUFFER_LINES, max_files = None):
    file_count = 0
    for path in os.listdir(f"{data_dir}/{channel_name}/transcripts/"):
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
    return "".join([character for character in a_str if (character.isalnum() or character == " ")])

def make_clip(time_bounds, filename, phrase, channel_name, data_dir):
    video_id, title = filename.split("---")

    start_time = stamp_to_dt(time_bounds[0])
    end_time = stamp_to_dt(time_bounds[1])
    diff_seconds = (end_time-start_time).total_seconds()
    input_path = f"{data_dir}/{channel_name}/full_videos/{video_id}---{title}.mp4"
    phrase_dir = f"{data_dir}/{channel_name}/clips/{normalize_str(phrase)}"
    output_path = f"{phrase_dir}/{video_id}---{title}---{start_time.strftime('%H%M%S')}---{end_time.strftime('%H%M%S')}.mp4"

    if not os.path.exists(input_path):
        download_video(video_id, f"{data_dir}/{channel_name}/full_videos/")

    if not os.path.exists(phrase_dir):
        os.makedirs(phrase_dir)

    cmd_str = f"ffmpeg -ss {time_bounds[0]} -i \"{input_path}\" -c copy -t {diff_seconds} \"{output_path}\""
    os.system(cmd_str)

if __name__ == '__main__':
    directory = "H:/clips/"
    channel_name = "BretWeinsteinDarkHorse"
    phrase = "ivermectin"

    #get_subtitles(channel_name)
    clip_all_instances(phrase, channel_name, directory):

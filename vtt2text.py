"""
Convert YouTube subtitles(vtt) to human readable text.
Download only subtitles from YouTube with youtube-dl:
youtube-dl  --skip-download --convert-subs vtt <video_url>
Note that default subtitle format provided by YouTube is ass, which is hard
to process with simple regex. Luckily youtube-dl can convert ass to vtt, which
is easier to process.
To conver all vtt files inside a directory:
find . -name "*.vtt" -exec python vtt2text.py {} \;
"""

import sys
import re


def remove_tags(text):
    """
    Remove vtt markup tags
    """
    tags = [
        r'</c>',
        r'<c(\.color\w+)?>',
        r'<\d{2}:\d{2}:\d{2}\.\d{3}>',
    ]

    for pat in tags:
        text = re.sub(pat, '', text)

    # extract timestamp, only kep HH:MM
    text = re.sub(
        r'(\d{2}:\d{2}):\d{2}\.\d{3} --> .* align:start position:0%',
        r'\g<1>',
        text
    )

    text = re.sub(r'^\s+$', '', text, flags=re.MULTILINE)
    return text


def remove_header(lines):
    """
    Remove vtt file header
    """
    pos = -1
    for mark in ('##', 'Language: en',):
        if mark in lines:
            pos = lines.index(mark)
    lines = lines[pos+1:]
    return lines


def merge_duplicates(lines):
    """
    Remove duplicated subtitles. Duplacates are always adjacent.
    """
    last_timestamp = ''
    last_cap = ''
    for line in lines:
        if line == "":
            continue
        if re.match('^\d{2}:\d{2}$', line):
            if line != last_timestamp:
                yield line
                last_timestamp = line
        else:
            if line != last_cap:
                yield line
                last_cap = line


def merge_short_lines(lines):
    buffer = ''
    for line in lines:
        if line == "" or re.match('^\d{2}:\d{2}$', line):
            yield '\n' + line
            continue

        if len(line+buffer) < 80:
            buffer += ' ' + line
        else:
            yield buffer.strip()
            buffer = line
    yield buffer

def remove_remaining_stamps(lines):
    new_lines = []

    for line in lines:
        if not re.search(r'\d{2}:\d{2}', line):
            new_lines.append(line)

    return new_lines


def combine_and_remove_whitespace(lines):
    full_txt = ""

    for line in lines:
        if line.lstrip() != "":
            full_txt += " "
            full_txt += line.lstrip()

    return full_txt


def collapse_lines(lines):
    text = "\n".join(lines)
    text = remove_tags(text)
    lines = text.splitlines()
    lines = remove_header(lines)
    lines = merge_duplicates(lines)
    lines = list(lines)
    lines = merge_short_lines(lines)
    lines = list(lines)
    lines = remove_remaining_stamps(lines)
    text = combine_and_remove_whitespace(lines)

    return text


def convert(vtt_file_name, txt_name):
    with open(vtt_file_name, encoding='utf-8', errors="ignore") as f:
        lines = f.readlines()

    text = collapse_lines(lines)

    with open(txt_name, 'w', encoding='utf-8', errors="ignore") as f:
        f.write(text)
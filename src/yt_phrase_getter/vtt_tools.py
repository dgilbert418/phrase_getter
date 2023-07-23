import re

TIME_FORMAT = "\d\d:\d\d:\d\d\.\d\d\d"

def text_only(line):
    """
    Remove vtt markup tags
    """
    tags = [
        r'</c>',
        r'<c(\.color\w+)?>',
        r'<\d{2}:\d{2}:\d{2}\.\d{3}>',
        r'(\d{2}:\d{2}):\d{2}\.\d{3} --> .* align:start position:0%'
    ]

    for pat in tags:
        line = re.sub(pat, '', line)

    line = re.sub(r'\n', '', line)
    line = re.sub(r'^\s+$', '', line, flags=re.MULTILINE)
    return line

def get_timebound_in_line(line):
    timestamps = re.findall(TIME_FORMAT, line)

    if len(timestamps) == 0:
        return None
    else:
        return timestamps[0]

def process_lines(lines):
    timebounds = []
    lines_txt = []

    previous_singleton = None
    previous_timebound = "00:00:00.000"

    for line in lines:
        # if line is one of the chunks introducing new text
        if re.search(r'</c>', line):
            timebound = get_timebound_in_line(line)
            timebounds.append(timebound)
            previous_timebound = timebound
            lines_txt.append(text_only(line))

        # if the line is a singleton with no </c>
        if re.match(r'^\w+\n$', line):
            line_word = text_only(line)
            if line_word != previous_singleton:
                timebounds.append(previous_timebound)
                lines_txt.append(line_word)
                previous_singleton = line_word

    return timebounds, lines_txt

def convert_to_tsv(input_file, output_file):
    with open(input_file, encoding='utf-8', errors="ignore") as f:
        lines = f.readlines()

    timebounds, lines_txt = process_lines(lines)

    with open(output_file, 'w+', encoding='utf-8', errors='ignore') as f:
        f.write("start\ttext\n")
        for i in range(len(timebounds)):
            f.write(
                timebounds[i] + "\t" +
                lines_txt[i] + "\n"
            )


if __name__ == '__main__':
    convert_to_tsv(
        "H:/clips/BenShapiro/transcripts/_FF7nlWQuRU---Ben Shapiro Breaks Down the Kyle Rittenhouse Trial.en.vtt",
        "H:/clips/BenShapiro/transcripts_tsv/_FF7nlWQuRU---Ben Shapiro Breaks Down the Kyle Rittenhouse Trial.tsv"
    )

#def text_only(line):

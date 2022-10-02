# phrase_getter
collect clips of phrases from a youtube channel

modify main with desired parameters, e.g.

```
directory = "H:/clips/" #  target directory for downloaded videos and clips  
channel_name = "BretWeinsteinDarkHorse"   
phrase = "lockdown"  
buffer_lines = 45 # number of transcript lines before and after the target phrase to include in each clip
```

then run 

```
get_catalog(channel_name, directory)  
get_all_subtitles(channel_name, directory)  
clip_all_instances(phrase, channel_name, directory, buffer_lines)  
```

catalog and subtitles only need to be collected once per channel. For each clip, the downloader will download the full video from youtube if it doesn't already exist in the directory.

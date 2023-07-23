# phrase_getter
collect clips of phrases from a youtube channel

run from command line:

```python phrase_getter.py {phrase} {channel_name} --output_directory "C:/phrase_getter/"``` 

example:

```python phrase_getter.py "game theory" "BretWeinsteinDarkHorse" -o "C:/phrase_getter/"``` 

Then find the clips in:

```C:/phrase_getter/BretWeinsteinDarkHorse/clips/game theory/```

The first time you run this program for each YouTube channel, phrase_getter will have to
download all of the subtitles from the channel's history, which will take a few minutes.
phrase_getter will skip this step if subtitles already exist in the subtitles folder of the
output directory.

Whenever phrase_getter runs, it searches the channel's transcript history for instances
of the phrase. Whenever it finds an instance, it must download the full video before
making the clip. If the full video has already been downloaded, phrase_getter will skip
to making the clip. Therefore, if you search for a common phrase on a new channel, 
phrase_getter will spend a long time downloading videos. The more you use phrase_getter on
a single channel, the fewer full videos it will need to download for future phrases.


import eng_to_ipa as ipa

IPA_VISEME_TABLE = {
    "b": "p", "d": "t", "ʤ": "S", "ð": "T", "f": "f", "g": "k",
    "h": "k", "j": "i", "k": "k", "l": "t", "m": "p", "n": "t",
    "ŋ": "k", "p": "p", "ɹ": "r", "s": "s", "ʃ": "S", "t": "t",
    "t͡ʃ": "S", "θ": "T", "v": "f", "w": "u", "z": "s", "ʒ": "S",
    "ə": "@", "ɚ": "@", "æ": "a", "aɪ": "a", "aʊ": "a", "ɑ": "a",
    "eɪ": "e", "ɝ": "E", "ɛ": "E", "i": "i", "ɪ": "i", "oʊ": "o",
    "ɔ": "O", "ɔɪ": "O", "u": "u", "ʊ": "u", "ʌ": "E", "ˈ": "ˈ",
}


def ipa_to_viseme(word):
    i = 0
    vis = ""
    while i < len(word):
        if (i < len(word) - 1) and ((word[i] + word[i+1]) in IPA_VISEME_TABLE):
            vis += IPA_VISEME_TABLE[word[i] + word[i+1]]
            i += 2
        elif word[i] in IPA_VISEME_TABLE:
            vis += IPA_VISEME_TABLE[word[i]]
            i += 1
        else:
            vis += word[i]
            i += 1
    return vis


def txt_to_viseme(txt):
    words_vis = []
    for word in txt.split(" "):
        word_ipa = ipa.convert(word)
        words_vis.append(ipa_to_viseme(word_ipa))

    return " ".join(words_vis)
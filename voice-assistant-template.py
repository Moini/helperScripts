from collections import deque
import math
from os import path, remove, system
import time

import pyaudio
import wave
import audioop

from pocketsphinx import Decoder, DefaultConfig, get_model_path
from sphinxbase.sphinxbase import *

from ttspico import TtsEngine

# Microphone stream config.
CHUNK = 1024  # CHUNKS of bytes to read each time from mic
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
THRESHOLD = 1000  #  The threshold intensity that defines silence
                  # and noise signal (an int. lower than THRESHOLD is silence).

SILENCE_LIMIT = 1  # Silence limit in seconds. The max ammount of seconds where
                   # only silence is recorded. When this time passes the
                   # recording finishes and the file is delivered.

PREV_AUDIO = 1.0  # Previous audio (in seconds) to prepend. When noise
                  # is detected, how much of previously recorded audio is
                  # prepended. This helps to prevent chopping the beggining
                  # of the phrase.
HOTWORD_THRESHOLD = -5000 # Higher values indicate that pocketsphinx
                          # is sure about the word. Adjust to your needs.
# Pocketsphinx files
MODELDIR = get_model_path() # Default model path, replace if
                            # you use a custom model in a custom location.

# WORDS
HOTWORD = "Anastasia"
SPEAK_UNDERSTOOD = "Understood."
SPEAK_FAILURE = "Sorry?"
SPEAK_SUCCESS = "Okay."
SPEAK_READY = HOTWORD + ". At your service."

# Decoder setup
config = DefaultConfig()
config.set_string('-hmm', path.join(MODELDIR, 'en-us'))
# you can use a custom model
config.set_string('-lm', path.join(MODELDIR, 'en-us.lm.bin'))
# you can use a custom dictionary
config.set_string('-dict', path.join(MODELDIR, 'cmudict-en-us.dict'))
# config.set_string('-logfn', '/dev/null')
decoder = Decoder(config)

# TTS settings and setup
engine = TtsEngine('en-US')
engine.pitch = 80 # 50 - 200
engine.rate = 120 # speed of speech, 20 - 500
# engine.volume = xx # 0 - 500

def play_synthesized(data_format, data, fin):
    print(data_format, len(data), fin)

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=1,
                    rate=RATE,
                    output=True,
                    frames_per_buffer=CHUNK)


    for i in range(0, len(data), CHUNK):
        stream.write(data[i:i+CHUNK])

    stream.close()
    p.terminate()

#
# Take the few moments at startup to gauge audio intensity of room.
#
def audio_int(num_samples=50):
    print(">>Getting intensity values from mic..")
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    values = [math.sqrt(abs(audioop.avg(stream.read(CHUNK), 4)))
              for x in range(num_samples)]
    values = sorted(values, reverse=True)
    r = sum(values[:int(num_samples * 0.2)]) // int(num_samples * 0.2)
    print(">>Finished. Average audio intensity is " + str(r))
    stream.close()
    p.terminate()
    return r

#
# Main Looping function, continually listens for sound and parses out string commands.
#
def listen_for_speech(threshold=THRESHOLD, num_phrases=-1):

    p = pyaudio.PyAudio()
    # Input
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print("\n>>Listening..")
    audio2send = []
    cur_data = ''
    rel = RATE/CHUNK
    slid_win = deque(maxlen=int(SILENCE_LIMIT * rel))

    #Prepend audio from 0.5 seconds before noise was detected
    prev_audio = deque(maxlen=int(PREV_AUDIO * rel))
    started = False
    listen_for_commands = 0
    n = num_phrases
    response = []

    # MAIN LOOP
    while (num_phrases == -1 or n > 0):
        cur_data = stream.read(CHUNK)
        slid_win.append(math.sqrt(abs(audioop.avg(cur_data, 4))))

        # print volume indicator
        # print(max(slid_win))

        # Basically build up audio in 1024 increments until you hear silence
        if(sum([x > THRESHOLD for x in slid_win]) > 0):
            if(not started):
                started = True
            audio2send.append(cur_data)
        elif (started is True):
            print(">>Finished")

            # The limit was reached, finish capture and deliver.
            tmp_filename = save_speech(list(prev_audio) + audio2send, p)
            # Transcribe file using pocketsphinx
            r = stt_pocketsphinx(tmp_filename)
            if num_phrases == -1:
                print(">>DEBUG Response: ", r)
                if listen_for_commands > 0:
                    if r.pop > -3500:
                        audio = engine.speak(SPEAK_UNDERSTOOD, play_synthesized)
                        print(SPEAK_UNDERSTOOD)
                        listen_for_commands = 0
                        parse_commands(r)
                    else:
                        audio = engine.speak(SPEAK_FAILURE, play_synthesized)
                        print(">>Didn't quite catch that.. try " + listen_for_commands)
                        listen_for_commands = listen_for_commands-1
                # If we found the hotword in listen stream and are sure.
                ### TODO: does not appear to work XXX
            elif HOTWORD.casefold() in r and r.pop > HOTWORD_THRESHOLD:
                    print('Found ' + HOTWORD)
                    audio = engine.speak(SPEAK_SUCCESS, play_synthesized)
                    # Listen is a Semaphore, allows us to try twice if we feel like we didn't understand first time.
                    listen_for_commands = 2;
            # Remove temp file.
            remove(tmp_filename)
            # Reset all
            started = False
            slid_win = deque(maxlen=int(SILENCE_LIMIT * rel))
            prev_audio = deque(maxlen=int(0.5 * rel))
            audio2send = []
            n -= 1
            print(">>Listening..")
        else:
            # If
            prev_audio.append(cur_data)

    stream.close()
    p.terminate()
    return response

# STUB, please write your own.
# Handed a list of repsonses, will look for command strings and execute commands.
#
def parse_commands(response):
    return True

#
# Transcribe audio file to text with Pocketsphinx..
#
def stt_pocketsphinx(wav_file):
    decoder.start_utt()
    stream = open(wav_file, "rb")
    while True:
        buf = stream.read(1024)
        if buf:
            decoder.process_raw(buf, False, False)
        else:
            break
    decoder.end_utt()
    words = []
    [words.append(seg.word) for seg in decoder.seg()]
    if decoder.hyp() != None:
        hypothesis = decoder.hyp()
        print ('Best hypothesis: ', hypothesis.hypstr, " model score: ", hypothesis.best_score, " confidence: ", hypothesis.prob)
        words.append(hypothesis.best_score)
    else:
        words.append(0)
    return words

#
# Writes Data to tmp WAV files for easy debugging..
#
def save_speech(data, p):
    filename = 'output_'+str(int(time.time()))
    data = b''.join(data)
    wf = wave.open(filename + '.wav', 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(16000)
    wf.writeframes(data)
    wf.close()
    return filename + '.wav'

#
# FUNCTION WHERE EVERYTHING STARTS
#
if(__name__ == '__main__'):
    temp = audio_int()
    # Set trigger threshold 10% above room volume level.
    threshold = temp + (temp * .10)
    audio = engine.speak(SPEAK_READY, play_synthesized)
    listen_for_speech(threshold, -1)
    print(">>Exiting.. \n")

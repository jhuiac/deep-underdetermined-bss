# -*- coding: utf-8 -*-
import numpy as np
import random
import soundfile as sf
from scipy.signal import decimate
from python_speech_features import sigproc


FRAME_LENGTH = .032
FRAME_SHIFT = .008
TIMESTEPS = 100


def squared_hann(M):
    return np.sqrt(np.hanning(M))


def stft(sig, rate):
	"""
	python_speech_features.sigproc.framesig(sig, frame_len, frame_step, winfunc=<function <lambda>>)
	Frame a signal into overlapping frames.

	Parameters:	
	sig – the audio signal to frame.
	frame_len – length of each frame measured in samples.
	frame_step – number of samples after the start of the previous frame that the next frame should begin.
	winfunc – the analysis window to apply to each frame. By default no window is applied.
	Returns:	
	an array of frames. Size is NUMFRAMES by frame_len.
	"""
    frames = sigproc.framesig(sig,
                              FRAME_LENGTH*rate,
                              FRAME_SHIFT*rate,
                              winfunc=squared_hann)
    spec = np.fft.rfft(frames, int(FRAME_LENGTH*rate))
    # adding 1e-7 just to avoid problems with log(0)
    return np.log10(np.absolute(spec)+1e-7)  # Log 10 for easier dB calculation


def get_egs(wavlist, min_mix=2, max_mix=3, sil_as_class=True, batch_size=1):
    """
    Generate examples for the neural network from a list of wave files with
    speaker ids. Each line is of type "path speaker", as follows:

    path/to/1st.wav spk1
    path/to/2nd.wav spk2
    path/to/3rd.wav spk1

    and so on.
    min_mix and max_mix are the minimum and maximum number of examples to
    be mixed for generating a training example

    sil_as_class defines if the threshold-defined background silence will
    be treated as a separate class
    """
    speaker_wavs = {}
    batch_x = []
    batch_y = []
    batch_count = 0
    while True:  # Generate examples indefinitely
        # Select number of files to mix
        k = np.random.randint(min_mix, max_mix+1)
        if k > len(speaker_wavs):
            # Reading wav files list and separating per speaker
            speaker_wavs = {}
            f = open(wavlist)
            for line in f:
                line = line.strip().split()
                if len(line) != 2:
                    continue
                p, spk = line
                if spk not in speaker_wavs:
                    speaker_wavs[spk] = []
                speaker_wavs[spk].append(p)
            f.close()
            # Randomizing wav lists
            for spk in speaker_wavs:
                random.shuffle(speaker_wavs[spk])
        wavsum = None
        sigs = []
        # Pop wav files from random speakers, store them individually for
        # dominant spectra decision and generate the mixed input
        for spk in random.sample(speaker_wavs.keys(), k):
            p = speaker_wavs[spk].pop()
            if not speaker_wavs[spk]:
                del(speaker_wavs[spk])  # Remove empty speakers from dictionary
            sig, rate = sf.read(p)
            if not(rate == 8000):
                sig = decimate(sig, rate//8000)
                rate = 8000
            sig = sig - np.mean(sig)
            sig = sig/np.max(np.abs(sig))
            sig *= (np.random.random()*1/4 + 3/4)
            if wavsum is None:
                wavsum = sig
            else:
                wavsum = wavsum[:len(sig)] + sig[:len(wavsum)]
            sigs.append(sig)

        # STFT for mixed signal
        X = stft(wavsum, rate)
        if len(X) <= TIMESTEPS:
            continue

        # STFTs for individual signals
        specs = []
        for sig in sigs:
            specs.append(stft(sig[:len(wavsum)], rate))
        specs = np.array(specs)

        if sil_as_class:
            nc = k + 1
        else:
            nc = k

        # Get dominant spectra indexes, create one-hot outputs
        Y = np.zeros(X.shape + (nc,))
        vals = np.argmax(specs, axis=0)
        for i in range(k):
            t = np.zeros(nc)
            t[i] = 1
            Y[vals == i] = t

        # EXPERIMENTAL: normalize mag spectra as weighted norm vectors instead
        # of using unit vectors for "hard" classes
#        if sil_as_class:
#            print("This won't work with sil_as_class=True")
#        from sklearn.preprocessing import normalize
#        Y = np.transpose(specs, (1, 2, 0))
#        Y = Y.reshape((-1, nc))
#        Y = normalize(Y, axis=1)
#        Y = Y.reshape(X.shape + (nc,))

        # Create mask for zeroing out gradients from silence components
        m = np.max(X) - 40./20  # Minus 40dB
        if sil_as_class:
            z = np.zeros(nc)
            z[-1] = 1
            Y[X < m] = z
        else:
            z = np.zeros(nc)
            Y[X < m] = z
        i = 0
        # Generating sequences
        while i + TIMESTEPS < len(X):
            # only chuncks with more than 40% of bins classified as speech
            # will be used.
            if np.sum(Y[i:i+TIMESTEPS]) / (Y[i:i+TIMESTEPS].size/nc) < 0.2:
                i += TIMESTEPS//2
                continue
            batch_x.append(X[i:i+TIMESTEPS])
            batch_y.append(Y[i:i+TIMESTEPS])
            i += TIMESTEPS//2

            batch_count = batch_count+1
            if batch_count == batch_size:
                #print "Generated new sample!"
                yield((np.array(batch_x).reshape((batch_size, TIMESTEPS, -1))),(np.array(batch_y).reshape((batch_size, TIMESTEPS, -1))))
                batch_x = []
                batch_y = []
                batch_count = 0
                break


if __name__ == "__main__":
    a = get_egs('wavlist_short', 2, 2, False)
    k = 6
    for i, j in a:
        print(i.shape, j.shape)
        print(j[0][0])
        k -= 1
        if k == 0:
            break

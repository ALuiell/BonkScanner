from __future__ import annotations

import ctypes
import struct
from threading import Lock
from typing import TYPE_CHECKING, Dict

from .importer import import_pyfmodex

try:
    import numpy as np
except ImportError:
    np = None

if TYPE_CHECKING:
    import pyfmodex
    import pyfmodex.enums
    import pyfmodex.flags
    import pyfmodex.structure_declarations
else:
    pyfmodex = import_pyfmodex()


SYSTEM_INSTANCES = {}  # (channels, flags) -> (pyfmodex_system_instance, lock)
SYSTEM_GLOBAL_LOCK = Lock()


def get_pyfmodex_system_instance(channels: int, flags: pyfmodex.flags.INIT_FLAGS):
    global pyfmodex, SYSTEM_INSTANCES, SYSTEM_GLOBAL_LOCK
    with SYSTEM_GLOBAL_LOCK:
        instance_key = (channels, flags)
        if instance_key in SYSTEM_INSTANCES:
            return SYSTEM_INSTANCES[instance_key]

        system = pyfmodex.System()
        system.init(channels, flags, None)
        lock = Lock()
        SYSTEM_INSTANCES[instance_key] = (system, lock)
        return system, lock


def raw_to_wav(
    raw_data: bytes, name: str, channels: int, frequency: int, convert_pcm_float: bool = True
) -> Dict[str, bytes]:
    """
    Loads the `raw_data` into a pyfmodex sound object and exports its subsounds to WAV files.
    Supports fsb as well as some other formats, but not RIFF bank files.

    Parameters:
        raw_data (bytes): The raw audio data to load.
        name (str): The base name of the output WAV files.
        channels (int): The number of audio channels to use for the system.
        frequency (int): The audio sample frequency to use for the system.
        convert_pcm_float (bool): Whether to convert PCM float to integer.

    Returns:
        Dict[str, bytes]: A dictionary mapping WAV file names to their byte data.
    """
    system, lock = get_pyfmodex_system_instance(channels, pyfmodex.flags.INIT_FLAGS.NORMAL)
    with lock:
        sound: pyfmodex.sound.Sound = system.create_sound(
            bytes(raw_data),
            pyfmodex.flags.MODE.OPENMEMORY,
            exinfo=pyfmodex.structure_declarations.CREATESOUNDEXINFO(
                length=len(raw_data),
                numchannels=channels,
                defaultfrequency=frequency,
            ),
        )

        samples = sound_to_wav(sound, name, convert_pcm_float)

        sound.release()
    return samples


def sound_to_wav(sound: pyfmodex.sound.Sound, name: str, convert_pcm_float: bool = True) -> Dict[str, bytes]:
    """
    Exports the subsounds of a pyfmodex sound object to WAV files.

    Parameters:
        sound (pyfmodex.sound.Sound): The sound object to convert.
        name (str): The base name of the output WAV files.
        convert_pcm_float (bool): Whether to convert PCM float to integer.

    Returns:
        Dict[str, bytes]: A dictionary mapping WAV file names to their byte data.
    """
    samples = {}
    for i in range(sound.num_subsounds):
        if i > 0:
            filename = f"{name}-{i}.wav"
        else:
            filename = f"{name}.wav"
        subsound = sound.get_subsound(i)
        samples[filename] = subsound_to_wav(subsound, convert_pcm_float)
        subsound.release()
    return samples


def subsound_to_wav(subsound: pyfmodex.sound.Sound, convert_pcm_float: bool = True) -> bytes:
    """
    Exports a pyfmodex sound object to WAV format.

    Parameters:
        subsound (pyfmodex.sound.Sound): The sound object to convert.
        convert_pcm_float (bool): Whether to convert PCM float to integer.

    Returns:
        bytes: The byte data of the WAV file.
    """
    # get sound settings
    sound_format = subsound.format.format  # pyright: ignore[reportAttributeAccessIssue]
    sound_data_length = subsound.get_length(pyfmodex.enums.TIMEUNIT.PCMBYTES)
    channels = subsound.format.channels  # pyright: ignore[reportAttributeAccessIssue]
    bits = subsound.format.bits  # pyright: ignore[reportAttributeAccessIssue]
    sample_rate = int(subsound.default_frequency)

    if sound_format in [
        pyfmodex.enums.SOUND_FORMAT.PCM8,
        pyfmodex.enums.SOUND_FORMAT.PCM16,
        pyfmodex.enums.SOUND_FORMAT.PCM24,
        pyfmodex.enums.SOUND_FORMAT.PCM32,
    ]:
        # format is PCM integer
        audio_format = 1
        wav_data_length = sound_data_length
        convert_pcm_float = False
    elif sound_format == pyfmodex.enums.SOUND_FORMAT.PCMFLOAT:
        # format is IEEE 754 float
        if convert_pcm_float:
            audio_format = 1
            bits = 16
            wav_data_length = sound_data_length // 2
        else:
            audio_format = 3
            wav_data_length = sound_data_length
    else:
        raise NotImplementedError("Sound format " + sound_format + " is not supported.")

    # create a WAV file in memory
    raw_wav_data = bytearray(wav_data_length + 40)

    # RIFF header - 0:12
    struct.pack_into(
        "<4si4s",
        raw_wav_data,
        0,
        b"RIFF",  # chunk id
        wav_data_length + 36,  # chunk size
        # 4 + (8 + 16 (sub chunk 1 size)) + (8 + length (sub chunk 2 size))
        b"WAVE",  # format
    )

    # fmt chunk - sub chunk 1, 12:36
    struct.pack_into(
        "<4sihhiihh",
        raw_wav_data,
        12,
        b"fmt ",  # sub chunk 1 id
        16,  # sub chunk 1 size, 16 for PCM
        audio_format,  # audio format, 1: PCM integer, 3: IEEE 754 float
        channels,  # number of channels
        sample_rate,  # sample rate
        sample_rate * channels * bits // 8,  # byte rate
        channels * bits // 8,  # block align
        bits,  # bits per sample
    )

    # data chunk - sub chunk 2
    struct.pack_into(
        "<4si",
        raw_wav_data,
        36,
        b"data",  # sub chunk 2 id
        wav_data_length,  # sub chunk 2 size
    )
    # sub chunk 2 data
    offset = 44
    lock = subsound.lock(0, sound_data_length)
    for ptr, sound_data_length in lock:
        ptr_data = ctypes.string_at(ptr, sound_data_length.value)
        if convert_pcm_float:
            # convert float to int16
            ptr_data = convert_pcm_float_to_pcm_int16(ptr_data)

        raw_wav_data[offset : offset + sound_data_length.value] = ptr_data
        offset += len(ptr_data)

    subsound.unlock(*lock)

    return bytes(raw_wav_data)


def convert_pcm_float_to_pcm_int16(ptr_data: bytes) -> bytes:
    if np is not None:
        values = np.frombuffer(ptr_data, dtype=np.float32)
        ptr_data = (values * (1 << 15)).clip(-32768, 32767).astype(np.int16).tobytes()
    else:
        values = struct.unpack("<%df" % (len(ptr_data) // 4), ptr_data)
        v_min = 1 / -32768
        v_max = 1 / 32767
        values = [-32768 if v < v_min else 32767 if v > v_max else int(v * (1 << 15)) for v in values]
        ptr_data = struct.pack("<%dh" % len(ptr_data), *values)

    return ptr_data


__all__ = [
    "get_pyfmodex_system_instance",
    "raw_to_wav",
    "sound_to_wav",
    "subsound_to_wav",
]

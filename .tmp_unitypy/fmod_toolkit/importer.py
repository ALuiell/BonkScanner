import ctypes
import os
import platform
from typing import TYPE_CHECKING, Literal, cast, get_args

SYSTEMS = Literal["Windows", "Linux", "Darwin"]
ARCHS = Literal["x64", "x86", "arm", "arm64"]

if TYPE_CHECKING:
    import pyfmodex
else:
    pyfmodex = None


def import_pyfmodex():
    global pyfmodex
    if pyfmodex is not None:
        return pyfmodex

    if not os.getenv("PYFMODEX_DLL_PATH"):
        fmod_path = get_fmod_path_for_system()
        os.environ["PYFMODEX_DLL_PATH"] = fmod_path

    if platform.system() != "Windows":
        # hotfix ctypes for pyfmodex for non windows systems
        ctypes.windll = None

    import pyfmodex

    return pyfmodex


def get_fmod_path_for_system():
    system = platform.system()
    arch = platform.architecture()[0]
    machine = platform.machine()

    if "arm" in machine:
        arch = "arm"
    elif "aarch64" in machine:
        if system == "Linux":
            arch = "arm64"
        else:
            arch = "arm"
    elif arch == "32bit":
        arch = "x86"
    elif arch == "64bit":
        arch = "x64"

    if arch not in get_args(ARCHS):
        raise ValueError(f"Unsupported architecture: {arch}")
    arch = cast(ARCHS, arch)

    if system not in get_args(SYSTEMS):
        raise ValueError(f"Unsupported system: {system}")
    system = cast(SYSTEMS, system)

    return os.path.join(os.path.dirname(__file__), get_fmod_path_for_config(system, arch))


def get_fmod_path_for_config(
    system: SYSTEMS,
    arch: ARCHS,
) -> str:
    if system == "Darwin":
        # universal dylib
        return "libfmod/Darwin/libfmod.dylib"
    if system == "Windows":
        return f"libfmod/Windows/{arch}/fmod.dll"
    if system == "Linux":
        arch_f = arch if arch != "x64" else "x86_64"
        return f"libfmod/Linux/{arch_f}/libfmod.so"

    raise NotImplementedError(f"Unsupported system: {system}")


__all__ = [
    "SYSTEMS",
    "ARCHS",
    "import_pyfmodex",
    "get_fmod_path_for_system",
    "get_fmod_path_for_config",
]

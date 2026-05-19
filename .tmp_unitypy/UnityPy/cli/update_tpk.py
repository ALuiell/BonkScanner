import os
from io import BytesIO
from urllib.request import urlopen
from zipfile import ZipFile

from UnityPy.tools.TpkClassGenerator import generate_classes

URL = "https://nightly.link/AssetRipper/Tpk/workflows/type_tree_tpk/master/lzma_file.zip"
RESOURCE_PATH = os.path.join(os.path.dirname(__file__), "..", "resources")


def update_tpk():
    print("Updating TPK file...")
    print("\tDownloading...")
    with urlopen(URL) as response:
        if response.status != 200:
            raise Exception(f"Failed to download TPK file: {response.status} {response.reason}")
        zip_data = response.read()
    print("\tExtracting...")
    with ZipFile(BytesIO(zip_data)) as zip_file:
        zip_file.extract("lzma.tpk", path=RESOURCE_PATH)
    print("\tGenerating classes...")
    generate_classes()
    print("\tDone.")


__all__ = ["update_tpk"]

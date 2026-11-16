"""Load the bundled example recording for the Quick Guide."""
from functools import lru_cache

from app.guide_examples import RunExample, read_run_example
from ui.shared import resource_path


@lru_cache(maxsize=1)
def load_run_example() -> RunExample:
    return read_run_example(resource_path("media/guides/run-example.json.gz"))


def game_clock(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

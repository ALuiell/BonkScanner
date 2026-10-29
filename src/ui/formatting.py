"""Localized UI facade over the pure player-stat formatting projections."""
from functools import lru_cache, wraps

from projections import formatting as _formatting
from core.localization_context import using_translator
from ui.i18n import UiText, active_translator


class FormattedText(UiText):
    def __new__(cls, function, args, kwargs, rendered):
        instance = str.__new__(cls, rendered)
        instance.function, instance.args, instance.kwargs = function, args, kwargs
        instance._language = active_translator().cache_key
        instance._rendered = rendered
        return instance

    def render(self):
        translator = active_translator()
        if self._language != translator.cache_key:
            with using_translator(translator):
                self._rendered = self.function(*self.args, **self.kwargs)
            self._language = translator.cache_key
        return self._rendered

    def canonical(self):
        with using_translator(None):
            return self.function(*self.args, **self.kwargs)


@lru_cache(maxsize=None)
def __getattr__(name):
    function = getattr(_formatting, name)
    if not callable(function):
        return function

    @wraps(function)
    def localized(*args, **kwargs):
        current_function = getattr(_formatting, name)
        with using_translator(active_translator()):
            result = current_function(*args, **kwargs)
        return FormattedText(current_function, args, kwargs, result) if isinstance(result, str) else result

    return localized

"""Formatting for prices captured from visible Shady Guy offer cards."""


def format_shady_price(price: int | None) -> str:
    if price is None or price < 0:
        return '—'
    if price < 1000:
        return str(price)
    if price < 10000:
        whole, fraction = divmod(price // 100, 10)
        return f'{whole}.{fraction}k' if fraction else f'{whole}k'
    if price < 1000000:
        return f'{price // 1000}k'
    whole, fraction = divmod(price // 100000, 10)
    return f'{whole}.{fraction}m' if fraction else f'{whole}m'

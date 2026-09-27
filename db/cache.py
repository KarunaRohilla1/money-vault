from functools import lru_cache


def cache_data(func=None, domains=None, **kwargs):
    if func is None:
        return lambda wrapped: wrapped
    return func


def cache_resource(func=None, **_kwargs):
    if func is None:
        return lambda wrapped: lru_cache(maxsize=1)(wrapped)
    return lru_cache(maxsize=1)(func)


def clear_data_cache(domains=None):
    pass
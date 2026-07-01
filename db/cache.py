try:
    import streamlit as st
except ImportError:
    st = None


def cache_data(func=None, **kwargs):
    if st is None:
        if func is None:
            return lambda wrapped: wrapped
        return func

    decorator = st.cache_data(**kwargs)

    if func is None:
        return decorator

    return decorator(func)


def cache_resource(func=None, **kwargs):
    if st is None:
        if func is None:
            return lambda wrapped: wrapped
        return func

    decorator = st.cache_resource(**kwargs)

    if func is None:
        return decorator

    return decorator(func)


def clear_data_cache():
    if st is not None:
        st.cache_data.clear()

from functools import wraps

try:
    import streamlit as st
except ImportError:
    st = None


KNOWN_CACHE_DOMAINS = (
    "accounts",
    "categories",
    "cycles",
    "dashboard",
    "planning",
    "reports",
    "shared_bills",
    "shared_expenses",
    "transaction_shares",
    "transactions",
    "transfers",
    "vaults",
    "wishlist"
)

MODULE_CACHE_DOMAINS = {
    "db.accounts": ("accounts",),
    "db.categories": ("categories",),
    "db.dashboard": ("dashboard",),
    "db.financial_cycles": ("cycles",),
    "db.planning": ("planning",),
    "db.shared_bills": ("shared_bills",),
    "db.shared_expenses": ("shared_expenses",),
    "db.transaction_shares": ("transaction_shares",),
    "db.transactions": ("transactions",),
    "db.transfers": ("transfers",),
    "db.vaults": ("vaults",),
    "db.wishlist": ("wishlist",),
    "views.reports": ("reports",)
}


def normalize_domains(domains):
    if domains is None:
        return KNOWN_CACHE_DOMAINS

    if isinstance(domains, str):
        return (domains,)

    return tuple(
        dict.fromkeys(domains)
    )


def infer_domains(func):
    return MODULE_CACHE_DOMAINS.get(
        func.__module__,
        KNOWN_CACHE_DOMAINS
    )


def get_cache_versions(domains):
    normalized = normalize_domains(domains)

    if st is None or not hasattr(st, "session_state"):
        return tuple(
            (domain, 0)
            for domain in normalized
        )

    versions = st.session_state.setdefault(
        "_cache_domain_versions",
        {}
    )

    return tuple(
        (
            domain,
            versions.get(domain, 0)
        )
        for domain in normalized
    )


def cache_data(func=None, domains=None, **kwargs):
    if st is None:
        if func is None:
            return lambda wrapped: wrapped
        return func

    def decorate(wrapped):
        tracked_domains = normalize_domains(
            domains or infer_domains(wrapped)
        )
        function_cache_key = (
            f"{wrapped.__module__}.{wrapped.__qualname__}"
        )

        @st.cache_data(**kwargs)
        def cached_call(cache_key, cache_versions, *args, **call_kwargs):
            return wrapped(*args, **call_kwargs)

        @wraps(wrapped)
        def wrapper(*args, **call_kwargs):
            return cached_call(
                function_cache_key,
                get_cache_versions(tracked_domains),
                *args,
                **call_kwargs
            )

        if hasattr(cached_call, "clear"):
            wrapper.clear = cached_call.clear
        return wrapper

    if func is None:
        return decorate

    return decorate(func)


def cache_resource(func=None, **kwargs):
    if st is None:
        if func is None:
            return lambda wrapped: wrapped
        return func

    decorator = st.cache_resource(**kwargs)

    if func is None:
        return decorator

    return decorator(func)


def clear_data_cache(domains=None):
    if st is None:
        return

    versions = st.session_state.setdefault(
        "_cache_domain_versions",
        {}
    )

    for domain in normalize_domains(domains):
        versions[domain] = versions.get(domain, 0) + 1

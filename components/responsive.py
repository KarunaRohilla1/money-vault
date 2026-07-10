from html import escape


def mobile_label(label):
    return f'data-mobile-label="{escape(str(label), quote=True)}"'

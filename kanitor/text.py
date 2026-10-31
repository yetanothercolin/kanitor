"""Shared text sanitizing and terminal-cell measurement."""
import unicodedata


def clean(text):
    return ''.join(c for c in str(text) if c >= ' ' and unicodedata.category(c) != 'Cc')


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)

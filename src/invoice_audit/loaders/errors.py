"""Exceptions raised by loaders. Kept separate so every loader can import them without cycles."""


class LoaderError(Exception):
    """This document can't be read. The run carries on; the reason goes in the Processing Log."""


class NeedsReviewWithoutExtraction(Exception):
    """Readable, but not worth sending to Claude (e.g. a 200-page PDF). Marked Needs review, no API call."""

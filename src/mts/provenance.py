"""Distinguish accepted public text evidence from cached error responses."""

import re


def public_source(source):
    digest = source.get('sha256')
    return source.get('kind') == 'raw_html' and source.get('status_code') == 200 and isinstance(digest, str) and bool(
        re.fullmatch(r'[0-9a-f]{64}', digest))

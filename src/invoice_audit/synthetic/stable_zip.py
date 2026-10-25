"""Make Office files (which are zip archives) byte-identical between runs.

python-docx and openpyxl stamp each zip entry with the current time. Different bytes would mean a
different cache key, so a regenerated but otherwise identical invoice would be paid for again.
"""

import re
import zipfile
from io import BytesIO

FIXED = (2026, 1, 1, 0, 0, 0)


def stable_zip(data: bytes) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = item.external_attr
            content = source.read(item.filename)
            if item.filename == "docProps/core.xml":  # openpyxl writes "modified = now" here on every save
                content = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(<)", rb"\g<1>2026-01-01T00:00:00Z\2",
                                 content)  # fmt: skip
            target.writestr(info, content)
    return out.getvalue()

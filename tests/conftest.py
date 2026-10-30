"""Datenisolation (Verfassung §6, Review H-07): Tests schreiben Anlagendaten, Läufe und Szenarien.
Gegen die Betriebs-DB `fld_os` würden sie die echten FLD-Werte der Demo zurücksetzen — daher hart abbrechen."""
import os
from urllib.parse import urlparse

import pytest

_url = os.environ.get("FLD_DATABASE_URL", "")
if _url and not _url.startswith("memory://") and urlparse(_url).path.lstrip("/") == "fld_os":
    pytest.exit("Tests nie gegen die Betriebs-DB fld_os — FLD_DATABASE_URL auf fld_os_test setzen (siehe .checksrc)", returncode=2)

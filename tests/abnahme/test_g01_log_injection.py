"""G01 (Review H1) Logzeilen sind nicht fälschbar: Steuerzeichen aus dem URL-Pfad landen nie roh im Log."""
import logging

from tests.abnahme._client import call


def test_zeilenumbruch_im_pfad_faelscht_keine_logzeile(caplog):
    caplog.set_level(logging.INFO, logger="fldos.request")
    call("GET", "/api/v1/x%0Afake%20200%20request_id=angreifer%0D", headers={"X-Request-ID": "abnahme-g01"})
    zeilen = [r.getMessage() for r in caplog.records if r.name == "fldos.request"]
    assert zeilen, "Positivkontrolle: die Request-Zeile muss geloggt werden"
    for z in zeilen:
        assert "\n" not in z and "\r" not in z, repr(z)
        assert z.count("request_id=") == 1 and z.rstrip().endswith("request_id=abnahme-g01"), repr(z)

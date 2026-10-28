from io import BytesIO

from PIL import Image
import pytest

import report_upload


def test_image_extensions_are_validated_and_text_is_returned(monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color="white").save(buffer, format="PNG")
    monkeypatch.setattr(report_upload, "_ocr_image", lambda image: "Tooth 36 has caries.")

    report = report_upload.extract_report("scan.PNG", buffer.getvalue())

    assert report["report_type"] == "Uploaded image"
    assert report["patient_name"] == "scan.PNG"
    assert report["findings"] == ["Tooth 36 has caries."]


def test_image_extension_must_match_content(monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color="white").save(buffer, format="PNG")
    monkeypatch.setattr(report_upload, "_ocr_image", lambda image: "Some text")

    with pytest.raises(ValueError, match="do not match"):
        report_upload.extract_report("scan.jpg", buffer.getvalue())


def test_unsupported_upload_extension_is_rejected():
    with pytest.raises(ValueError, match="Supported report formats"):
        report_upload.extract_report("report.doc", b"not supported")

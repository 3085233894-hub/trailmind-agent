from __future__ import annotations


def test_calculate_geometry_distance_km():
    from app.tools.gpx_tool import calculate_geometry_distance_km

    geometry = [
        [30.0, 120.0],
        [30.01, 120.01],
    ]

    distance = calculate_geometry_distance_km(geometry)

    assert distance > 0
    assert distance < 3


def test_geometry_to_gpx_string_contains_track_points():
    from app.tools.gpx_tool import geometry_to_gpx_string

    geometry = [
        [30.0, 120.0],
        [30.01, 120.01],
    ]

    gpx_text = geometry_to_gpx_string(
        geometry=geometry,
        name="pytest路线",
    )

    assert "<?xml" in gpx_text
    assert "<gpx" in gpx_text
    assert "<trkpt" in gpx_text
    assert 'lat="30.0"' in gpx_text
    assert 'lon="120.0"' in gpx_text


def test_parse_gpx_bytes():
    from app.tools.gpx_tool import parse_gpx_bytes

    gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>pytest-gpx</name>
    <trkseg>
      <trkpt lat="30.0" lon="120.0"></trkpt>
      <trkpt lat="30.01" lon="120.01"></trkpt>
    </trkseg>
  </trk>
</gpx>
"""

    result = parse_gpx_bytes(
        file_bytes=gpx.encode("utf-8"),
        filename="test.gpx",
    )

    assert result["ok"] is True
    assert result["name"] == "pytest-gpx"
    assert result["geometry_points"] == 2
    assert result["geometry"][0] == [30.0, 120.0]


def test_parse_kml_bytes():
    from app.tools.gpx_tool import parse_kml_bytes

    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>pytest-kml</name>
    <Placemark>
      <LineString>
        <coordinates>
          120.0,30.0,0 120.01,30.01,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

    result = parse_kml_bytes(
        file_bytes=kml.encode("utf-8"),
        filename="test.kml",
    )

    assert result["ok"] is True
    assert result["name"] == "pytest-kml"
    assert result["geometry_points"] == 2
    assert result["geometry"][0] == [30.0, 120.0]


def test_parse_uploaded_track_file_builds_trail():
    from app.tools.gpx_tool import parse_uploaded_track_file

    gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>pytest-track</name>
    <trkseg>
      <trkpt lat="30.0" lon="120.0"></trkpt>
      <trkpt lat="30.01" lon="120.01"></trkpt>
    </trkseg>
  </trk>
</gpx>
"""

    result = parse_uploaded_track_file(
        file_bytes=gpx.encode("utf-8"),
        filename="pytest.gpx",
        user_level="新手",
    )

    assert result["ok"] is True
    assert result["trail"]["name"] == "pytest-track"
    assert result["trail"]["source_type"] == "uploaded_gpx"
    assert result["trail"]["distance_km"] > 0
    assert result["trail"]["estimated_duration_hours"] is not None
    assert result["trail"]["geometry_points"] == 2
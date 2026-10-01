import sqlite3
import struct

import numpy as np
from openpyxl import Workbook
from app import (
    ExailParser,
    PhlinStreamParser,
    RAOManager,
    SEA_STATE_PRESETS,
    SQLiteLogger,
    StdBinStreamParser,
    compute_wave,
    determine_reception_quality,
    simulate_sea_state,
)


def make_phlin_frame(x, y, heave):
    body = f"PHLIN,{x:.3f},{y:.3f},{heave:.3f}"
    checksum = 0
    for character in body.encode("ascii"):
        checksum ^= character
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


def make_stdbin_frame(heave):
    header = b"IX" + bytes([3])
    header += (1 << 2).to_bytes(4, "big")
    header += b"\x00" * 8
    header += (41).to_bytes(2, "big")
    header += b"\x00" * 8
    return header + struct.pack(">4f", 1.0, heave, 3.0, 4.0)


def test_stdbin_parser_extracts_heave_from_fragmented_stream():
    frame = make_stdbin_frame(2.5)
    parser = StdBinStreamParser()

    assert parser.feed(b"noise" + frame[:12]) == []
    assert parser.feed(frame[12:]) == [("heave", 2.5)]
    assert ExailParser.stdbin(frame) == ("heave", 2.5)


def test_phlin_parser_extracts_heave_from_fragmented_stream():
    frame = make_phlin_frame(1.234, 2.345, -3.456)
    parser = PhlinStreamParser()

    assert parser.feed(frame[:10]) == []
    assert parser.feed(frame[10:]) == [("heave", -3.456)]
    assert ExailParser.phlin(frame) == ("heave", -3.456)


def test_phlin_parser_rejects_invalid_checksum():
    frame = make_phlin_frame(1.234, 2.345, 3.456)
    invalid_frame = frame.replace(b"*", b"*00", 1)

    assert ExailParser.phlin(invalid_frame) is None


def test_wave_returns_valid_result():
    fs = 5.0
    t = np.arange(0, 20*60, 1/fs)
    x = 0.5*np.sin(2*np.pi*0.1*t)
    r = compute_wave(x, fs)
    assert r.valid
    assert r.hs_m > 0
    assert abs(r.tp_s - 10) < 1.0


def test_rao_manager_loads_heading_specific_excel_curves(tmp_path):
    workbook = Workbook()
    for heading, gains in (("0", (0.8, 0.4)), ("90", (0.6, 0.2))):
        sheet = workbook.active if heading == "0" else workbook.create_sheet(heading)
        sheet.title = heading
        sheet.cell(row=5, column=2, value=2.0)
        sheet.cell(row=5, column=5, value=gains[1])
        sheet.cell(row=6, column=2, value=4.0)
        sheet.cell(row=6, column=5, value=gains[0])
    filepath = tmp_path / "rao_iot.xlsx"
    workbook.save(filepath)

    rao = RAOManager(filepath)

    assert rao.available_headings == (0.0, 90.0)
    assert rao.get_gain(0.25) == 0.8
    assert rao.get_gain(0.1) == 1.0
    rao.set_heading(90)
    assert rao.get_gain(0.25) == 0.6


def test_rao_manager_loads_molene_excel_layout(tmp_path):
    workbook = Workbook()
    for heading, gain in (("0°", 0.8), ("90°", 0.6)):
        sheet = workbook.active if heading == "0°" else workbook.create_sheet(heading)
        sheet.title = heading
        sheet.cell(row=4, column=1, value="Period")
        sheet.cell(row=4, column=6, value="Heave")
        sheet.cell(row=7, column=1, value=4.0)
        sheet.cell(row=7, column=6, value=gain)
    filepath = tmp_path / "rao_molene.xlsx"
    workbook.save(filepath)

    rao = RAOManager(filepath)

    assert rao.available_headings == (0.0, 90.0)
    assert rao.get_gain(0.25) == 0.8
    rao.set_heading(90)
    assert rao.get_gain(0.25) == 0.6


def test_simulate_sea_state_has_realistic_variability():
    samples = [simulate_sea_state(i * 0.2) for i in range(600)]
    arr = np.asarray(samples, dtype=float)
    assert arr.std() > 0.1
    assert np.ptp(arr) > 0.5


def test_sea_state_presets_are_defined():
    assert set(SEA_STATE_PRESETS) == {"calm", "moderate", "rough", "instrument"}
    for key, cfg in SEA_STATE_PRESETS.items():
        assert cfg["swell_h"] > 0
        assert cfg["noise_std"] >= 0


def test_error_log_contains_entries(tmp_path):
    logger = SQLiteLogger(tmp_path)
    logger.start()
    logger.write_error("ERROR", "sensor", "Test message")
    logger.close()

    conn = sqlite3.connect(logger.db_path)
    count = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
    conn.close()
    assert count == 1


def test_reception_quality_levels_are_defined():
    assert determine_reception_quality(valid=True, missing_sensors=0, error_count=0) == "GOOD"
    assert determine_reception_quality(valid=False, missing_sensors=2, error_count=3) == "POOR"
    assert determine_reception_quality(valid=True, missing_sensors=1, error_count=1) == "MODERATE"

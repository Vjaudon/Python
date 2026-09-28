import json
import math
import queue
import random
import socket
import sqlite3
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
from scipy import signal
import serial

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

BASE = Path(__file__).resolve().parent

@dataclass
class WaveResult:
    hs_m: float = float("nan")
    tp_s: float = float("nan")
    valid: bool = False
    timestamp: float = 0.0

# ==========================================
# GESTION DES DONNÉES (SQLite & RAO)
# ==========================================

class SQLiteLogger:
    """Remplace le CSVLogger pour plus de robustesse et d'intégrité."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.db_path = self.directory / f"asn_measurements_{stamp}.sqlite"
        self.conn = None

    def start(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                timestamp_utc TEXT,
                heave_m REAL,
                current_speed_kn REAL,
                current_direction_deg REAL,
                current_depth_m REAL,
                wind_speed_kn REAL,
                wind_direction_deg REAL,
                hs_m REAL,
                tp_s REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                timestamp_utc TEXT,
                level TEXT,
                component TEXT,
                message TEXT
            )
        """)
        self.conn.commit()

    def write(self, data):
        if self.conn:
            self.conn.execute("""
                INSERT INTO measurements 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            self.conn.commit()

    def write_error(self, level, component, message):
        if self.conn:
            self.conn.execute(
                "INSERT INTO errors (timestamp_utc, level, component, message) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), level, component, message)
            )
            self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()


def determine_reception_quality(valid, missing_sensors=0, error_count=0):
    """Return a coarse quality label based on signal validity and sensor health."""
    if not valid and (missing_sensors >= 2 or error_count >= 3):
        return "POOR"
    if missing_sensors > 0 or error_count > 0:
        return "MODERATE"
    return "GOOD"

class RAOManager:
    """Gestionnaire de RAO (Response Amplitude Operator)."""
    def __init__(self, filepath=None):
        self.frequencies = []
        self.gains = []
        if filepath and Path(filepath).exists():
            self._load_rao(filepath)
            
    def _load_rao(self, filepath):
        # Stub pour le chargement d'un fichier CSV/JSON de RAO réel
        pass

    def get_gain(self, frequency):
        if not self.frequencies:
            return 1.0 # Pas de correction par défaut
        return np.interp(frequency, self.frequencies, self.gains)

# ==========================================
# ACQUISITION (Réseau, Série, Parseurs)
# ==========================================

class NMEAParser:
    @staticmethod
    def text(payload):
        return payload.decode("ascii", errors="ignore").strip()

    @staticmethod
    def heave(payload):
        s = NMEAParser.text(payload)
        parts = s.replace("*", ",").split(",")
        if parts and parts[0].upper().endswith("HEAVE") and len(parts) >= 2:
            return ("heave", float(parts[1]))
        return None
    # (Les autres parseurs NMEA restent similaires...)
    @staticmethod
    def current(payload):
        s = NMEAParser.text(payload)
        parts = s.replace("*", ",").split(",")
        if parts and parts[0].upper() in ("CURRENT", "CUR") and len(parts) >= 4:
            return ("current", float(parts[1]), float(parts[2]), float(parts[3]))
        return None

    @staticmethod
    def wind(payload):
        s = NMEAParser.text(payload)
        parts = s.replace("*", ",").split(",")
        if parts and parts[0].upper() in ("WIND", "MWV") and len(parts) >= 3:
            return ("wind", float(parts[1]), float(parts[2]))
        return None

class ExailParser:
    """Decodeur minimal du format binaire STDBIN Exail."""
    @staticmethod
    def phlin(payload):
        """Decode une trame $PHLIN et retourne le heave en metres."""
        try:
            sentence = payload.decode("ascii").strip()
            if not sentence.startswith("$") or "*" not in sentence:
                return None

            body, checksum = sentence[1:].rsplit("*", 1)
            if len(checksum) != 2:
                return None
            expected = 0
            for character in body.encode("ascii"):
                expected ^= character
            if int(checksum, 16) != expected:
                return None

            fields = body.split(",")
            if len(fields) != 4 or fields[0].upper() != "PHLIN":
                return None
            return ("heave", float(fields[3]))
        except (UnicodeDecodeError, ValueError):
            return None

    @staticmethod
    def stdbin(payload):
        """Decode une trame STDBIN complete et retourne le heave en metres."""
        if len(payload) < 32 or payload[:2] != b"IX":
            return None

        try:
            offset = 2
            version = payload[offset]
            offset += 1
            nav_mask = int.from_bytes(payload[offset:offset + 4], "big")
            offset += 4
            offset += 8  # extended navigation mask and extended mask
            if version > 3:
                offset += 2  # navigation block size
            total_size = int.from_bytes(payload[offset:offset + 2], "big")
            offset += 2

            if total_size < offset + 8 or len(payload) < total_size:
                return None

            offset += 8  # INS timestamp and telegram counter
            if nav_mask & (1 << 0):
                offset += 12
            if nav_mask & (1 << 1):
                offset += 12
            if not nav_mask & (1 << 2) or offset + 16 > total_size:
                return None

            heave = struct.unpack_from(">4f", payload, offset)[1]
            return ("heave", float(heave))
        except (IndexError, struct.error, ValueError):
            return None

    @staticmethod
    def bacustom2(payload):
        """Alias retained for configurations naming the Exail output BACUSTOM2."""
        return ExailParser.stdbin(payload)


class StdBinStreamParser:
    """Accumulate un flux binaire et extrait les trames STDBIN completes."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, payload):
        self.buffer.extend(payload)
        results = []
        while True:
            sync_idx = self.buffer.find(b"IX")
            if sync_idx < 0:
                if self.buffer.endswith(b"I"):
                    self.buffer[:] = b"I"
                else:
                    self.buffer.clear()
                break
            if sync_idx:
                del self.buffer[:sync_idx]
            if len(self.buffer) < 17:
                break

            version = self.buffer[2]
            size_offset = 15 if version <= 3 else 17
            if len(self.buffer) < size_offset + 2:
                break
            total_size = int.from_bytes(self.buffer[size_offset:size_offset + 2], "big")
            if total_size < size_offset + 2:
                del self.buffer[:2]
                continue
            if len(self.buffer) < total_size:
                break

            frame = bytes(self.buffer[:total_size])
            del self.buffer[:total_size]
            item = ExailParser.stdbin(frame)
            if item:
                results.append(item)
        return results


class PhlinStreamParser:
    """Accumulate un flux texte et extrait les trames $PHLIN completes."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, payload):
        self.buffer.extend(payload)
        results = []
        while b"\n" in self.buffer:
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            item = ExailParser.phlin(line)
            if item:
                results.append(item)
        return results

class UDPReceiver(threading.Thread):
    def __init__(self, port, out_queue, decoder, bind_host="0.0.0.0", source_host=None):
        super().__init__(daemon=True)
        self.port = port
        self.out_queue = out_queue
        self.decoder = decoder
        self.bind_host = bind_host
        self.source_host = source_host
        self.stop_event = threading.Event()

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.port))
        sock.settimeout(0.5)
        try:
            while not self.stop_event.is_set():
                try:
                    payload, source = sock.recvfrom(65535)
                    if self.source_host and source[0] != self.source_host:
                        continue
                    item = self.decoder(payload)
                    if item:
                        self.out_queue.put((*item, time.time()))
                except socket.timeout:
                    continue
                except Exception as exc:
                    self.out_queue.put(("error", f"UDP {self.port}: {exc}"))
        finally:
            sock.close()
            
    def stop(self):
        self.stop_event.set()

class SerialReceiver(threading.Thread):
    """Acquisition sur port série (RS232/RS422)."""
    def __init__(self, port, baudrate, out_queue, decoder, stream_parser=None):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.out_queue = out_queue
        self.decoder = decoder
        self.stream_parser = stream_parser
        self.stop_event = threading.Event()

    def run(self):
        try:
            with serial.Serial(self.port, self.baudrate, timeout=0.5) as ser:
                while not self.stop_event.is_set():
                    payload = ser.read(ser.in_waiting or 1)
                    if not payload:
                        continue
                    if self.stream_parser:
                        items = self.stream_parser.feed(payload)
                    else:
                        item = self.decoder(payload)
                        items = [item] if item else []
                    for item in items:
                        self.out_queue.put((*item, time.time()))
        except Exception as exc:
            self.out_queue.put(("error", f"Serial {self.port}: {exc}"))

    def stop(self):
        self.stop_event.set()

# ==========================================
# TRAITEMENT DU SIGNAL EN ARRIÈRE-PLAN
# ==========================================

def compute_wave(heaves, sample_rate_hz, rao_manager=None, fmin=0.03, fmax=0.5):
    """Fonction mathématique pure, isolée des threads."""
    x = np.asarray(heaves, dtype=float)
    if len(x) < max(32, int(sample_rate_hz * 60)):
        return WaveResult()

    x = signal.detrend(x)
    nperseg = min(len(x), max(256, int(sample_rate_hz * 256)))
    freqs, psd = signal.welch(x, fs=sample_rate_hz, window="hann", nperseg=nperseg, detrend="constant")

    mask = (freqs >= fmin) & (freqs <= fmax)
    freqs, psd = freqs[mask], psd[mask]

    if len(freqs) < 3:
        return WaveResult()

    if rao_manager is None:
        gain = np.ones_like(freqs, dtype=float)
    else:
        gain = np.asarray([max(float(rao_manager.get_gain(f)), 1e-6) for f in freqs])
    psd = psd / (gain ** 2)

    m0 = np.trapezoid(psd, freqs) if hasattr(np, "trapezoid") else np.trapz(psd, freqs)
    if not np.isfinite(m0) or m0 <= 0:
        return WaveResult()

    peak_idx = int(np.argmax(psd))
    fp = float(freqs[peak_idx])
    tp = 1.0 / fp if fp > 0 else float("nan")
    hs = 4.0 * math.sqrt(m0)
    return WaveResult(hs, tp, True, time.time())

class WaveProcessor(threading.Thread):
    """Thread dédié pour ne pas bloquer l'interface UI (Tkinter)."""
    def __init__(self, data_lock, heave_deque, sample_rate, result_queue, config, rao_manager):
        super().__init__(daemon=True)
        self.data_lock = data_lock
        self.heave_deque = heave_deque
        self.sample_rate = sample_rate
        self.result_queue = result_queue
        self.config = config
        self.rao_manager = rao_manager
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            # Copie rapide sous verrou pour minimiser le blocage
            with self.data_lock:
                heave_copy = list(self.heave_deque)
            
            if heave_copy:
                result = compute_wave(
                    heave_copy, 
                    self.sample_rate, 
                    self.rao_manager,
                    fmin=self.config["wave"]["min_frequency_hz"],
                    fmax=self.config["wave"]["max_frequency_hz"]
                )
                self.result_queue.put(result)
            
            # Ne recalcule le spectre que toutes les 2 secondes
            time.sleep(2.0)

    def stop(self):
        self.stop_event.set()

# ==========================================
# SIMULATEUR & INTERFACE GRAPHIQUE
# ==========================================

SEA_STATE_PRESETS = {
    "calm": {
        "swell_h": 0.18,
        "chop_h": 0.08,
        "drift_h": 0.05,
        "noise_std": 0.015,
        "current_speed": 0.5,
        "wind_speed": 6.0,
    },
    "moderate": {
        "swell_h": 0.42,
        "chop_h": 0.15,
        "drift_h": 0.10,
        "noise_std": 0.025,
        "current_speed": 1.1,
        "wind_speed": 14.0,
    },
    "rough": {
        "swell_h": 0.85,
        "chop_h": 0.30,
        "drift_h": 0.18,
        "noise_std": 0.04,
        "current_speed": 2.0,
        "wind_speed": 25.0,
    },
    "instrument": {
        "swell_h": 0.25,
        "chop_h": 0.12,
        "drift_h": 0.05,
        "noise_std": 0.08,
        "current_speed": 1.0,
        "wind_speed": 12.0,
    },
}


def simulate_sea_state(time_s, phase=0.0, preset="moderate"):
    """Generate a configurable sea-state signal with swell, chop, drift and noise."""
    config = SEA_STATE_PRESETS.get(preset, SEA_STATE_PRESETS["moderate"])
    swell = config["swell_h"] * math.sin(2 * math.pi * 0.09 * time_s + phase)
    chop = config["chop_h"] * math.sin(2 * math.pi * 0.18 * time_s + phase * 1.7)
    low_freq_drift = config["drift_h"] * math.sin(2 * math.pi * 0.03 * time_s + phase * 0.6)
    modulation = 1.0 + 0.25 * math.sin(2 * math.pi * 0.04 * time_s + phase * 0.8)
    noise = random.gauss(0.0, config["noise_std"])
    return (swell + chop + low_freq_drift) * modulation + noise


class Simulator(threading.Thread):
    """Générateur de données plus réaliste pour le mode simulation."""
    def __init__(self, out_queue, sample_rate=5.0, preset="moderate"):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.sample_rate = sample_rate
        self.preset = preset
        self.stop_event = threading.Event()
        self.t = 0.0
        self.phase = random.random() * 6.28
        self.config = SEA_STATE_PRESETS.get(preset, SEA_STATE_PRESETS["moderate"])

    def run(self):
        dt = 1.0 / self.sample_rate
        while not self.stop_event.is_set():
            wave = simulate_sea_state(self.t, phase=self.phase, preset=self.preset)
            current_speed = self.config["current_speed"] * (1.0 + 0.20 * math.sin(2 * math.pi * 0.02 * self.t))
            wind_speed = self.config["wind_speed"] * (1.0 + 0.18 * math.sin(2 * math.pi * 0.015 * self.t))

            now = time.time()
            self.out_queue.put(("heave", wave, now))
            self.out_queue.put(("current", current_speed, 210, 2.5, now))
            self.out_queue.put(("wind", wind_speed, 250, now))

            self.t += dt
            time.sleep(dt)

    def stop(self):
        self.stop_event.set()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASN Wave Monitor")
        self.geometry("1250x780")
        self.config_data = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        
        self.queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.data_lock = threading.Lock()
        
        self.sample_rate = 5.0
        self.heave = deque(maxlen=int(self.sample_rate * 20 * 60))
        
        self.history_t = deque(maxlen=1800)
        self.history_hs = deque(maxlen=1800)
        self.history_tp = deque(maxlen=1800)
        
        self.current = {"speed": float("nan"), "direction": float("nan"), "depth": float("nan")}
        self.wind = {"speed": float("nan"), "direction": float("nan")}
        self.wave = WaveResult()

        self.logger = SQLiteLogger(BASE / self.config_data["storage"]["directory"])
        self.logger.start()
        self.rao = RAOManager(self.config_data["wave"].get("rao_file"))

        self.build_ui()
        self.start_inputs()
        self.after(self.config_data["app"]["refresh_ms"], self.tick)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        """Construction de l'interface (simplifiée ici pour la lisibilité)."""
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="ASN Wave Monitor", font=("Segoe UI", 20, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="Démarrage…")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        cards = ttk.Frame(self, padding=10)
        cards.pack(fill="x")
        self.vars = {
            "Hs": (tk.StringVar(value="—"), "m"),
            "Tp": (tk.StringVar(value="—"), "s"),
            "Courant": (tk.StringVar(value="—"), "kn"),
            "Vent": (tk.StringVar(value="—"), "kn")
        }
        for title, (var, unit) in self.vars.items():
            f = ttk.LabelFrame(cards, text=title, padding=12)
            f.pack(side="left", fill="both", expand=True, padx=5)
            ttk.Label(f, textvariable=var, font=("Segoe UI", 22, "bold")).pack()
            ttk.Label(f, text=unit).pack()

        self.alert_var = tk.StringVar(value="NORMAL")
        self.quality_var = tk.StringVar(value="GOOD")
        self.error_log_messages = deque(maxlen=20)
        self.sensor_status_vars = {}
        self.sensor_status_labels = {}

        alert = ttk.LabelFrame(self, text="État des seuils", padding=8)
        alert.pack(fill="x", padx=15)
        ttk.Label(alert, textvariable=self.alert_var, font=("Segoe UI", 14, "bold")).pack(side="left")

        quality = ttk.LabelFrame(self, text="Qualité de réception", padding=8)
        quality.pack(fill="x", padx=15, pady=(0, 8))
        self.quality_label = ttk.Label(quality, textvariable=self.quality_var, font=("Segoe UI", 14, "bold"))
        self.quality_label.pack(side="left")

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        sensor_panel = ttk.LabelFrame(bottom, text="État des capteurs", padding=8)
        sensor_panel.pack(side="left", fill="y", padx=(0, 8))
        self.sensor_listbox = tk.Listbox(sensor_panel, width=24, height=5, exportselection=False)
        self.sensor_listbox.pack(fill="y", expand=True)
        self.sensor_listbox.insert(tk.END, "Octans")
        self.sensor_listbox.insert(tk.END, "Courant")
        self.sensor_listbox.insert(tk.END, "Vent")
        self.sensor_listbox.bind("<<ListboxSelect>>", self.on_sensor_select)

        self.sensor_details = tk.StringVar(value="Sélectionnez un capteur")
        ttk.Label(sensor_panel, textvariable=self.sensor_details, wraplength=220, justify="left").pack(fill="x", pady=(8, 0))

        log = ttk.LabelFrame(bottom, text="Journal d'erreurs", padding=8)
        log.pack(side="left", fill="both", expand=True)
        self.error_log_box = tk.Text(log, height=8, wrap="word", state="disabled", bg="#f7f7f7")
        self.error_log_box.pack(side="left", fill="both", expand=True)
        yscroll = tk.Scrollbar(log, orient="vertical", command=self.error_log_box.yview)
        yscroll.pack(side="right", fill="y")
        self.error_log_box.configure(yscrollcommand=yscroll.set)

        self.fig = Figure(figsize=(11, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def start_inputs(self):
        self.workers = []
        mode = self.config_data["inputs"].get("mode", "simulation")
        
        if mode == "simulation":
            preset = self.config_data["inputs"].get("preset", "moderate")
            sim = Simulator(self.queue, self.sample_rate, preset=preset)
            self.workers.append(sim)
            self.status_var.set(f"Simulation active ({preset})")
        else:
            # Exemple de lancement hybride UDP/Série basé sur la config
            for sensor, cfg in self.config_data["inputs"].items():
                if sensor in ("mode", "preset"): continue
                is_octans = sensor == "octans"
                parser = (ExailParser.phlin if is_octans else
                          NMEAParser.wind if sensor == "wind" else NMEAParser.current)
                if cfg["transport"] == "udp":
                    w = UDPReceiver(
                        cfg["port"],
                        self.queue,
                        parser,
                        cfg.get("local_host", "0.0.0.0"),
                        cfg.get("host"),
                    )
                elif cfg["transport"] == "serial":
                    stream_parser = PhlinStreamParser() if is_octans else None
                    w = SerialReceiver(cfg["port"], cfg["baudrate"], self.queue, parser, stream_parser)
                self.workers.append(w)
            self.status_var.set("Acquisition capteurs active")

        for w in self.workers:
            w.start()

        # Démarrage du thread de calcul lourd
        self.processor = WaveProcessor(self.data_lock, self.heave, self.sample_rate, self.result_queue, self.config_data, self.rao)
        self.processor.start()

    def tick(self):
        """Boucle principale UI, extrêmement légère."""
        error_count = 0
        missing_sensors = 0

        while True:
            try:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "error":
                    error_count += 1
                    msg = str(item[1])
                    self.logger.write_error("ERROR", "sensor", msg)
                    self.error_log_messages.append(msg)
                    self._append_error_log(msg)
                    continue
                if kind == "heave":
                    with self.data_lock:
                        self.heave.append(float(item[1]))
                elif kind == "current":
                    self.current.update(speed=float(item[1]), direction=float(item[2]), depth=float(item[3]))
                elif kind == "wind":
                    self.wind.update(speed=float(item[1]), direction=float(item[2]))
            except queue.Empty:
                break

        if len(self.heave) == 0:
            missing_sensors += 1
        if not np.isfinite(self.current["speed"]):
            missing_sensors += 1
        if not np.isfinite(self.wind["speed"]):
            missing_sensors += 1

        try:
            while True:
                self.wave = self.result_queue.get_nowait()
                self.history_t.append(datetime.now().strftime("%H:%M:%S"))
                self.history_hs.append(self.wave.hs_m if self.wave.valid else np.nan)
                self.history_tp.append(self.wave.tp_s if self.wave.valid else np.nan)
                self.update_dashboard(error_count=error_count, missing_sensors=missing_sensors)
                self._log_current_state()
        except queue.Empty:
            pass

        if not self.history_hs:
            self.update_dashboard(error_count=error_count, missing_sensors=missing_sensors)

        self._update_sensor_status_summary(error_count=error_count, missing_sensors=missing_sensors)
        self.after(self.config_data["app"]["refresh_ms"], self.tick)

    def _log_current_state(self):
        heave_val = self.heave[-1] if self.heave else None
        timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.logger.write((
            timestamp_utc,
            heave_val,
            self.current["speed"], self.current["direction"], self.current["depth"],
            self.wind["speed"], self.wind["direction"],
            self.wave.hs_m if self.wave.valid else None,
            self.wave.tp_s if self.wave.valid else None
        ))

    def on_sensor_select(self, event=None):
        selection = self.sensor_listbox.curselection()
        if not selection:
            return
        name = self.sensor_listbox.get(selection[0])
        self.sensor_details.set(f"{name}: {self.sensor_status_vars.get(name, 'UNKNOWN')}")

    def _append_error_log(self, message):
        self.error_log_box.configure(state="normal")
        self.error_log_box.insert(tk.END, message + "\n")
        self.error_log_box.see(tk.END)
        self.error_log_box.configure(state="disabled")

    def _update_sensor_status_summary(self, error_count=0, missing_sensors=0):
        sensor_status = {
            "Octans": "GOOD" if len(self.heave) > 0 else "POOR",
            "Courant": "GOOD" if np.isfinite(self.current["speed"]) else "POOR",
            "Vent": "GOOD" if np.isfinite(self.wind["speed"]) else "POOR",
        }

        if error_count > 0:
            sensor_status["Octans"] = "MODERATE" if sensor_status["Octans"] != "POOR" else "POOR"

        for name, status in sensor_status.items():
            self.sensor_status_vars[name] = status
            self.sensor_listbox.itemconfig(self.sensor_listbox.get(0, tk.END).index(name), bg={"GOOD": "#c8e6c9", "MODERATE": "#ffe0b2", "POOR": "#ffcdd2"}[status])

        selected = self.sensor_listbox.curselection()
        if selected:
            name = self.sensor_listbox.get(selected[0])
            self.sensor_details.set(f"{name}: {sensor_status.get(name, 'UNKNOWN')}")

    def update_dashboard(self, error_count=0, missing_sensors=0):
        self.vars["Hs"][0].set(f"{self.wave.hs_m:.2f}" if self.wave.valid else "—")
        self.vars["Tp"][0].set(f"{self.wave.tp_s:.1f}" if self.wave.valid else "—")

        quality = determine_reception_quality(self.wave.valid, missing_sensors=missing_sensors, error_count=error_count)
        self.quality_var.set(f"{quality} ({missing_sensors} missing / {error_count} errors)")
        colors = {"GOOD": ("#2e7d32", "white"), "MODERATE": ("#f9a825", "black"), "POOR": ("#c62828", "white")}
        bg, fg = colors.get(quality, ("#2e7d32", "white"))
        self.quality_label.configure(background=bg, foreground=fg, padding=(12, 4))

        a = self.config_data["alerts"]
        alarms = []
        if self.wave.valid and self.wave.hs_m > a["hs_max_m"]: alarms.append("Hs")
        if np.isfinite(self.wind["speed"]) and self.wind["speed"] > a["wind_max_kn"]: alarms.append("Vent")
        if quality == "POOR": alarms.append("Reception")
        if quality == "MODERATE": alarms.append("Qualité faible")

        self.alert_var.set("ALERTE: " + ", ".join(alarms) if alarms else "NORMAL")

        self.ax.clear()
        x = list(self.history_t)
        self.ax.plot(x, self.history_hs, label="Hs (m)")
        self.ax.plot(x, self.history_tp, label="Tp (s)")
        self.ax.grid(True, alpha=0.25)
        self.ax.legend(loc="upper left")
        if len(x) > 1:
            step = max(1, len(x) // 8)
            self.ax.set_xticks(range(0, len(x), step))
            self.ax.set_xticklabels(x[::step], rotation=30)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def on_close(self):
        for w in self.workers: w.stop()
        if hasattr(self, 'processor'): self.processor.stop()
        self.logger.close()
        self.destroy()

if __name__ == "__main__":
    App().mainloop()
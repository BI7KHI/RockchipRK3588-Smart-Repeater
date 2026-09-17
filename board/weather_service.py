#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ELF2 气象数据服务：RS485 / Modbus RTU 风力变送器采集与记录。"""
import sqlite3
import struct
import threading
import time
from datetime import datetime
from pathlib import Path


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _truthy(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'on', 'yes', 'y')


def _modbus_request(addr, func, register, quantity):
    body = bytes([
        addr & 0xFF, func & 0xFF,
        (register >> 8) & 0xFF, register & 0xFF,
        (quantity >> 8) & 0xFF, quantity & 0xFF,
    ])
    return body + struct.pack('<H', crc16(body))


class WeatherService:
    def __init__(self, db_path, csv_dir='/www/weather_csv'):
        self.db_path = str(db_path)
        self.csv_dir = Path(csv_dir)
        try:
            self.csv_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.lock = threading.RLock()
        self.settings = {}
        self.stop_event = threading.Event()
        self.thread = None
        self.status = {
            'running': False,
            'last_ok': 0,
            'last_error': '',
            'last_raw': None,
            'last_speed': None,
            'last_ts': '',
            'last_tx_hex': '',
            'last_rx_hex': '',
            'poll_count': 0,
            'error_count': 0,
            'rain_last_ok': 0,
            'rain_last_error': '',
            'rain_last_raw': None,
            'rain_last_total': None,
            'rain_last_ts': '',
            'rain_last_tx_hex': '',
            'rain_last_rx_hex': '',
            'rain_poll_count': 0,
            'rain_error_count': 0,
        }
        try:
            self.ensure_schema()
        except Exception:
            pass

    def _parse_modbus_response(self, buf, addr, func):
        """从接收缓冲区中扫描出合法的 Modbus RTU 响应帧。"""
        n = len(buf)
        i = 0
        while i <= n - 5:
            if buf[i] != addr:
                i += 1
                continue
            f = buf[i + 1]
            if f & 0x80:
                # 异常响应: addr, func|0x80, exception_code, crc_lo, crc_hi
                frame = buf[i:i + 5]
                calc = crc16(frame[:-2])
                got = frame[-2] | (frame[-1] << 8)
                if calc == got:
                    return {'values': [], 'frame': frame.hex(), 'offset': i, 'exception': frame[2]}
                i += 1
                continue
            if f != func:
                i += 1
                continue
            if i + 3 > n:
                break
            byte_count = buf[i + 2]
            frame_len = 3 + byte_count + 2
            if i + frame_len > n:
                i += 1
                continue
            frame = buf[i:i + frame_len]
            calc = crc16(frame[:-2])
            got = frame[-2] | (frame[-1] << 8)
            if calc != got:
                i += 1
                continue
            values = []
            for j in range(byte_count // 2):
                values.append((frame[3 + j * 2] << 8) | frame[4 + j * 2])
            return {'values': values, 'frame': frame.hex(), 'offset': i}
        return None

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        return c

    def _append_csv(self, ts, ts_epoch, wind_speed, raw):
        """按日生成/追加 CSV，便于历史调用和导出。"""
        try:
            day = ts[:10]
            path = self.csv_dir / f'wind_{day}.csv'
            new = not path.exists()
            with open(path, 'a', encoding='utf-8-sig', newline='') as f:
                if new:
                    f.write('时间,时间戳,风速(m/s),raw,单位\n')
                f.write(f'{ts},{ts_epoch},{wind_speed},{raw},m/s\n')
        except Exception:
            pass

    def _append_rain_csv(self, ts, ts_epoch, rain_total, raw):
        """按日生成/追加降水量 CSV（累计值）。"""
        try:
            day = ts[:10]
            path = self.csv_dir / f'rain_{day}.csv'
            new = not path.exists()
            with open(path, 'a', encoding='utf-8-sig', newline='') as f:
                if new:
                    f.write('时间,时间戳,累计降水量(mm),raw,单位\n')
                f.write(f'{ts},{ts_epoch},{rain_total},{raw},mm\n')
        except Exception:
            pass

    def history_range(self, days=7, interval_minutes=10):
        """查询最近 N 天并按 interval_minutes 分钟聚合。"""
        days = max(1, int(days))
        interval_minutes = max(1, int(interval_minutes))
        bucket = interval_minutes * 60
        start = int(time.time()) - days * 86400
        with self._conn() as c:
            rows = c.execute(
                'SELECT (? * (ts_epoch / ?)) AS bucket, '
                'AVG(wind_speed) AS avg_speed, MAX(wind_speed) AS max_speed, '
                'MIN(wind_speed) AS min_speed, COUNT(*) AS n '
                'FROM weather_readings WHERE ts_epoch >= ? '
                'GROUP BY bucket ORDER BY bucket ASC',
                (bucket, bucket, start)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['ts'] = datetime.fromtimestamp(d['bucket']).strftime('%Y-%m-%d %H:%M')
            except Exception:
                d['ts'] = str(d.get('bucket'))
            result.append(d)
        return result

    def ensure_schema(self):
        with self._conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS weather_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                ts_epoch INTEGER NOT NULL,
                wind_speed REAL,
                raw INTEGER,
                unit TEXT DEFAULT 'm/s',
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_weather_ts_epoch ON weather_readings(ts_epoch);
            CREATE INDEX IF NOT EXISTS idx_weather_ts ON weather_readings(ts);

            CREATE TABLE IF NOT EXISTS rain_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                ts_epoch INTEGER NOT NULL,
                rain_total REAL,
                raw INTEGER,
                unit TEXT DEFAULT 'mm',
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rain_ts_epoch ON rain_readings(ts_epoch);
            CREATE INDEX IF NOT EXISTS idx_rain_ts ON rain_readings(ts);
            ''')

    def update_settings(self, settings):
        with self.lock:
            self.settings = dict(settings or {})

    def start(self, settings=None):
        if settings:
            self.update_settings(settings)
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.status['running'] = True
                return True, 'already running'
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            self.status['running'] = True
            return True, 'started'

    def restart(self, settings=None):
        self.stop()
        return self.start(settings)

    def stop(self):
        self.stop_event.set()
        t = self.thread
        if t and t.is_alive():
            t.join(timeout=3)
        with self.lock:
            self.status['running'] = False
        return True, 'stopped'

    def read_once(self, settings=None):
        s = dict(self.settings)
        if settings:
            s.update(settings)
        port = s.get('port', '/dev/ttyS9')
        baud = int(float(s.get('baud', 9600) or 9600))
        parity = str(s.get('parity', 'N') or 'N')
        stopbits = int(float(s.get('stopbits', 1) or 1))
        timeout = float(s.get('timeout', 1.0) or 1.0)
        addr = int(float(s.get('slave', 1) or 1))
        func = int(float(s.get('function', 3) or 3))
        register = int(float(s.get('register', 0) or 0))
        quantity = int(float(s.get('quantity', 1) or 1))
        scale = float(s.get('scale', 0.1) or 0.1)

        import serial
        ser = serial.Serial(port=port, baudrate=baud, bytesize=8,
                            parity=parity, stopbits=stopbits, timeout=timeout)
        try:
            req = _modbus_request(addr, func, register, quantity)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(req)
            ser.flush()
            # 不假设固定长度，持续读取直到超时，再从缓冲区中扫描合法帧
            rx = b''
            deadline = time.time() + max(0.4, timeout)
            while time.time() < deadline:
                chunk = ser.read(256)
                if chunk:
                    rx += chunk
                # 尝试解析已有数据
                parsed = self._parse_modbus_response(rx, addr, func)
                if parsed:
                    break
                if rx and len(rx) > 512:
                    break
            with self.lock:
                self.status['last_tx_hex'] = req.hex()
                self.status['last_rx_hex'] = rx.hex()
            parsed = self._parse_modbus_response(rx, addr, func)
            if not parsed:
                if not rx:
                    raise TimeoutError('未收到 Modbus 响应')
                raise ValueError(f'未解析到有效 Modbus 帧: TX={req.hex()} RX={rx.hex()}')
            values = parsed['values']
            raw = values[0] if values else None
            speed = round(raw * scale, 2) if raw is not None else None
            now = datetime.now()
            ts = now.strftime('%Y-%m-%d %H:%M:%S')
            ts_epoch = int(now.timestamp())
            with self.lock:
                self.status.update(last_ok=time.time(), last_error='', last_raw=raw,
                                   last_speed=speed, last_ts=ts, poll_count=self.status.get('poll_count', 0) + 1)
            with self._conn() as c:
                c.execute('INSERT INTO weather_readings(ts,ts_epoch,wind_speed,raw,unit) VALUES(?,?,?,?,?)',
                          (ts, ts_epoch, speed, raw, 'm/s'))
            self._append_csv(ts, ts_epoch, speed, raw)
            return {'ok': True, 'raw': raw, 'wind_speed': speed, 'values': values,
                    'ts': ts, 'ts_epoch': ts_epoch}
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def read_rain_once(self, settings=None):
        """读取翻斗式雨量计的累计降水量寄存器。"""
        s = dict(self.settings)
        if settings:
            s.update(settings)
        if not _truthy(s.get('rain_enabled', '1')):
            return {'ok': False, 'skipped': True}
        port = s.get('port', '/dev/ttyS9')
        baud = int(float(s.get('baud', 9600) or 9600))
        parity = str(s.get('parity', 'N') or 'N')
        stopbits = int(float(s.get('stopbits', 1) or 1))
        timeout = float(s.get('timeout', 1.0) or 1.0)
        addr = int(float(s.get('rain_slave', 23) or 23))
        func = int(float(s.get('rain_function', 3) or 3))
        register = int(float(s.get('rain_register', 0) or 0))
        quantity = max(1, min(10, int(float(s.get('rain_quantity', 1) or 1))))
        scale = float(s.get('rain_scale', 0.1) or 0.1)

        import serial
        ser = serial.Serial(port=port, baudrate=baud, bytesize=8,
                            parity=parity, stopbits=stopbits, timeout=timeout)
        try:
            req = _modbus_request(addr, func, register, quantity)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(req)
            ser.flush()
            rx = b''
            deadline = time.time() + max(0.4, timeout)
            while time.time() < deadline:
                chunk = ser.read(256)
                if chunk:
                    rx += chunk
                parsed = self._parse_modbus_response(rx, addr, func)
                if parsed:
                    break
                if rx and len(rx) > 512:
                    break
            with self.lock:
                self.status['rain_last_tx_hex'] = req.hex()
                self.status['rain_last_rx_hex'] = rx.hex()
            parsed = self._parse_modbus_response(rx, addr, func)
            if not parsed:
                if not rx:
                    raise TimeoutError('雨量计未收到 Modbus 响应')
                raise ValueError(f'雨量计未解析到有效帧: TX={req.hex()} RX={rx.hex()}')
            values = parsed['values']
            raw = values[0] if values else None
            rain_total = round(raw * scale, 2) if raw is not None else None
            now = datetime.now()
            ts = now.strftime('%Y-%m-%d %H:%M:%S')
            ts_epoch = int(now.timestamp())
            with self.lock:
                self.status.update(
                    rain_last_ok=time.time(), rain_last_error='',
                    rain_last_raw=raw, rain_last_total=rain_total, rain_last_ts=ts,
                    rain_poll_count=self.status.get('rain_poll_count', 0) + 1)
            with self._conn() as c:
                c.execute('INSERT INTO rain_readings(ts,ts_epoch,rain_total,raw,unit) VALUES(?,?,?,?,?)',
                          (ts, ts_epoch, rain_total, raw, 'mm'))
            self._append_rain_csv(ts, ts_epoch, rain_total, raw)
            return {'ok': True, 'raw': raw, 'rain_total': rain_total,
                    'values': values, 'ts': ts, 'ts_epoch': ts_epoch}
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _loop(self):
        self.ensure_schema()
        while not self.stop_event.is_set():
            try:
                self.read_once()
                with self.lock:
                    self.status['last_error'] = ''
            except Exception as e:
                with self.lock:
                    self.status['last_error'] = str(e)
                    self.status['error_count'] = self.status.get('error_count', 0) + 1
            try:
                if _truthy(self.settings.get('rain_enabled', '1')):
                    self.read_rain_once()
                    with self.lock:
                        self.status['rain_last_error'] = ''
            except Exception as e:
                with self.lock:
                    self.status['rain_last_error'] = str(e)
                    self.status['rain_error_count'] = self.status.get('rain_error_count', 0) + 1
            interval = float(self.settings.get('poll_interval', 2) or 2)
            self.stop_event.wait(max(1, interval))

    def realtime(self):
        with self.lock:
            return dict(self.status)

    def history(self, date_str, limit=5000):
        with self._conn() as c:
            rows = c.execute(
                'SELECT ts,ts_epoch,wind_speed,raw FROM weather_readings '
                'WHERE ts LIKE ? ORDER BY ts_epoch ASC LIMIT ?',
                (date_str + '%', limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def history_minute(self, date_str, interval_minutes=5):
        interval_minutes = max(1, int(interval_minutes))
        bucket = interval_minutes * 60
        with self._conn() as c:
            rows = c.execute(
                'SELECT (? * (ts_epoch / ?)) AS bucket, '
                'AVG(wind_speed) AS avg_speed, MAX(wind_speed) AS max_speed, '
                'MIN(wind_speed) AS min_speed, COUNT(*) AS n '
                'FROM weather_readings WHERE ts LIKE ? '
                'GROUP BY bucket ORDER BY bucket ASC',
                (bucket, bucket, date_str + '%')
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['minute'] = datetime.fromtimestamp(d['bucket']).strftime('%Y-%m-%d %H:%M')
            except Exception:
                d['minute'] = str(d.get('bucket'))
            result.append(d)
        return result

    def rain_hourly(self, date_str):
        """把翻斗式雨量计的累计值按小时差分，返回 24 个小时桶。

        翻斗式雨量计通常只输出累计降水量；小时雨量 = 本小时最后累计值
        - 本小时开始前累计值。跨小时/跨天用相邻样本差分实现。
        """
        try:
            day = datetime.strptime(str(date_str)[:10], '%Y-%m-%d')
        except Exception:
            day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_epoch = int(day.timestamp())
        end_epoch = start_epoch + 86400
        with self._conn() as c:
            prev = c.execute(
                'SELECT ts,ts_epoch,rain_total FROM rain_readings '
                'WHERE ts_epoch < ? AND rain_total IS NOT NULL '
                'ORDER BY ts_epoch DESC LIMIT 1',
                (start_epoch,)
            ).fetchone()
            rows = c.execute(
                'SELECT ts,ts_epoch,rain_total FROM rain_readings '
                'WHERE ts_epoch >= ? AND ts_epoch < ? AND rain_total IS NOT NULL '
                'ORDER BY ts_epoch ASC',
                (start_epoch, end_epoch)
            ).fetchall()
        buckets = [0.0] * 24
        samples = [0] * 24
        prev_total = prev['rain_total'] if prev else None
        for r in rows:
            total = r['rain_total']
            if total is None:
                continue
            if prev_total is None:
                delta = 0.0
            else:
                delta = float(total) - float(prev_total)
                if delta < 0:
                    # 设备重启或清零后，累计值从 0 开始
                    delta = float(total)
            if delta < 0:
                delta = 0.0
            hour = datetime.fromtimestamp(int(r['ts_epoch'])).hour
            buckets[hour] += delta
            samples[hour] += 1
            prev_total = total
        return [
            {
                'hour': f'{h:02d}:00',
                'hour_index': h,
                'rain_mm': round(buckets[h], 2),
                'samples': samples[h],
            }
            for h in range(24)
        ]

    def rain_stats(self, date_str):
        points = self.rain_hourly(date_str)
        total = round(sum(p['rain_mm'] for p in points), 2)
        max_point = max(points, key=lambda x: x['rain_mm']) if points else None
        max_mm = round(max_point['rain_mm'], 2) if max_point else 0.0
        return {
            'total_mm': total,
            'max_hour_mm': max_mm,
            'max_hour': max_point['hour'] if max_point else '',
            'points': points,
        }

    def rain_recent_hour(self):
        """最近 60 分钟降水量，按累计值差分计算。"""
        now = time.time()
        with self._conn() as c:
            rows = c.execute(
                'SELECT ts_epoch,rain_total FROM rain_readings '
                'WHERE ts_epoch >= ? AND rain_total IS NOT NULL '
                'ORDER BY ts_epoch ASC',
                (int(now - 3600),)
            ).fetchall()
        if len(rows) < 2:
            return 0.0
        total = 0.0
        prev = rows[0]['rain_total']
        for r in rows[1:]:
            cur = r['rain_total']
            if cur is None:
                continue
            delta = float(cur) - float(prev)
            if delta < 0:
                delta = float(cur)
            if delta > 0:
                total += delta
            prev = cur
        return round(total, 2)

    def stats(self, date_str):
        with self._conn() as c:
            row = c.execute(
                'SELECT COUNT(*) AS count, MAX(wind_speed) AS max_speed, MIN(wind_speed) AS min_speed, '
                'AVG(wind_speed) AS avg_speed FROM weather_readings WHERE ts LIKE ?',
                (date_str + '%',)
            ).fetchone()
            max_row = c.execute(
                'SELECT ts,wind_speed,raw FROM weather_readings WHERE ts LIKE ? '
                'ORDER BY wind_speed DESC, ts_epoch DESC LIMIT 1',
                (date_str + '%',)
            ).fetchone()
        return {
            'count': row['count'] if row else 0,
            'max_speed': round(row['max_speed'], 2) if row and row['max_speed'] is not None else None,
            'min_speed': round(row['min_speed'], 2) if row and row['min_speed'] is not None else None,
            'avg_speed': round(row['avg_speed'], 2) if row and row['avg_speed'] is not None else None,
            'max_time': max_row['ts'] if max_row else '',
            'max_raw': max_row['raw'] if max_row else None,
        }

    def cleanup(self, keep_days=90):
        cutoff = int(time.time()) - keep_days * 86400
        with self._conn() as c:
            c.execute('DELETE FROM weather_readings WHERE ts_epoch < ?', (cutoff,))
            c.execute('DELETE FROM rain_readings WHERE ts_epoch < ?', (cutoff,))

"""시험용 FIT 만들기(다이빙 1개 이상): file_id · record(1초마다 수심) · session · activity(현지 시차).
압축 시간 머리글도 섞음(실제 기기처럼). make_fit(dives=[(입수 UTC 초, [(초, 수심m), ...])], local_off=초)."""
import struct

FIT_EPOCH = 631065600


def _crc(data: bytes) -> int:
    tbl = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
           0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
    crc = 0
    for b in data:
        tmp = tbl[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ tbl[b & 0xF]
        tmp = tbl[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ tbl[(b >> 4) & 0xF]
    return crc


def make_fit(dives, local_off=9 * 3600, compressed=True) -> bytes:
    body = bytearray()

    def define(local, gm, fields):
        body.extend(bytes([0x40 | local, 0, 0]) + struct.pack("<H", gm) + bytes([len(fields)]))
        for num, size, bt in fields:
            body.extend(bytes([num, size, bt]))

    define(0, 0, [(0, 1, 0x00), (4, 4, 0x86)])                       # file_id: type, time_created
    body.extend(bytes([0]) + struct.pack("<BI", 4, dives[0][0] - FIT_EPOCH))
    define(1, 20, [(253, 4, 0x86), (92, 4, 0x86), (13, 1, 0x01)])     # record: timestamp, depth(mm), temp
    define(3, 20, [(92, 4, 0x86), (13, 1, 0x01)])                     # record(압축 시간용)
    last = 0
    for start, prof in dives:
        st = start - FIT_EPOCH
        for k, (t, d) in enumerate(prof):
            ts = st + int(t)
            if compressed and k % 3 and last and 0 < ts - last < 31:
                body.extend(bytes([0x80 | (3 << 5) | (ts & 0x1F)]) + struct.pack("<Ib", int(d * 1000), 27))
            else:
                body.extend(bytes([1]) + struct.pack("<IIb", ts, int(d * 1000), 27))
            last = ts
    define(2, 18, [(253, 4, 0x86), (2, 4, 0x86), (5, 1, 0x00), (6, 1, 0x00)])   # session: end, start, sport, sub
    for start, prof in dives:
        st = start - FIT_EPOCH
        body.extend(bytes([2]) + struct.pack("<IIBB", st + int(prof[-1][0]), st, 53, 53))
    define(4, 34, [(253, 4, 0x86), (5, 4, 0x86)])                     # activity: timestamp, local_timestamp
    end = dives[-1][0] - FIT_EPOCH + int(dives[-1][1][-1][0])
    body.extend(bytes([4]) + struct.pack("<II", end, end + local_off))
    hdr = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    hdr += struct.pack("<H", _crc(hdr))
    data = hdr + bytes(body)
    return data + struct.pack("<H", _crc(data))


def profile(minutes=40, max_d=22.0, pre=60):
    """입수 전 수면 pre 초 + 하강 2분 · 바닥 · 안전정지 5m 3분 · 출수. 1초마다."""
    out = []
    n = minutes * 60
    for t in range(0, pre + n + 30):
        u = t - pre
        if u < 0:
            d = 0.0
        elif u < 120:
            d = max_d * u / 120
        elif u < n - 300:
            d = max_d - 4 * ((u // 60) % 3)
        elif u < n - 240:
            d = 5 + (max_d - 9) * (n - 240 - u) / 60
        elif u < n - 60:
            d = 5.0
        elif u < n:
            d = 5.0 * (n - u) / 60
        else:
            d = 0.0
        out.append((t, round(d, 2)))
    return out

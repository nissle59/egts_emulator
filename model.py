import base64
import json
import pickle
from EGTStrack import EGTStrack
from pydantic import BaseModel


class Point(BaseModel):
    coordinatesId: int | float | None = None
    tid: int | None = None
    latitude: float
    longitude: float
    speed: int | None = 0
    angle: int = 0
    sleeper: bool = False
    sleep_time: int = 0
    timestamp: int | None = None
    regnumber: str | None = None

    def to_json(self):
        return json.dumps(self.to_dict())

    def to_dict(self):
        d = {
            "coordinatesId": self.coordinatesId,
            "tid": self.tid,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "speed": self.speed,
            "angle": self.angle,
            "sleeper": self.sleeper,
            "sleep_time": self.sleep_time,
            "timestamp": self.timestamp
        }
        try:
            d['regnumber'] = self.regnumber
        except:
            d['regnumber'] = None
        return d

    def to_b64(self):
        b_code = pickle.dumps(self)
        base64_bytes = base64.b64encode(b_code)
        base64_string = base64_bytes.decode('utf-8')
        return base64_string

    @classmethod
    def from_b64(cls, b64_string):
        if isinstance(b64_string, str):
            base64_bytes = b64_string.encode('utf-8')
        else:
            base64_bytes = b64_string
        b_code = base64.b64decode(base64_bytes)
        obj = pickle.loads(b_code)
        return obj

    def to_egts_packet(self, imei, offset=None):
        egts_instance = EGTStrack(deviceimei=imei)
        egts_instance.add_service(16,
                                  long=self.longitude,
                                  lat=self.latitude,
                                  speed=self.speed,
                                  angle=self.angle,
                                  offset=offset
                                  )
        message_b = egts_instance.new_message()
        return message_b

    @staticmethod
    def from_json_b(json_bstr):
        s = json.loads(json_bstr.decode('utf-8'))
        return Point(**s)

    def __repr__(self):
        return f"Point(speed {self.speed}, angle {self.angle}, lat[{self.latitude}] long[{self.longitude}])"


class Segment(BaseModel):
    segmentId: int
    taskId: int
    jamsTime: float = 0.0
    length: float = 0.0
    sleep: int | None = None
    coordinates: list[Point]


class Route(BaseModel):
    ok: bool
    results: list[Segment] | None = None
    error: str | None = None

    def __repr__(self):
        return json.dumps({ 'ok': self.ok, 'results': self.results, 'error': self.error })

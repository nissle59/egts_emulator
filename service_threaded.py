import datetime
import json
import logging
import math
import random
import socket
import time
import requests
from requests.auth import HTTPBasicAuth
import geopy
import pika
from pika.exceptions import ChannelClosedByBroker
import socks
import threading
import base64
import config
import model
from ApiService import ApiService
from EGTStrack import EGTStrack
from model import *
from config import MQ, sec_interval

LOGGER = logging.getLogger(__name__)
imeis = []

config.coord_id_now = 0


def interpolate_coordinates(point_a, point_b, fraction, cur_point):
    LOGGER = logging.getLogger(__name__ + ".interpolate_coordinates")
    """Интерполирует координаты между двумя точками."""
    config.coord_id_now += 1
    lat_diff = point_b.latitude - point_a.latitude
    lon_diff = point_b.longitude - point_a.longitude
    lat = point_a.latitude + fraction * lat_diff
    lon = point_a.longitude + fraction * lon_diff
    return Point(
        # coordinatesId=point_a.coordinatesId + 0.001 * cur_point,
        coordinatesId=config.coord_id_now,
        latitude=float("{0:.6f}".format(round(lat * 1000000) / 1000000)),
        longitude=float("{0:.6f}".format(round(lon * 1000000) / 1000000))
    )


def adjust_control_points(segment):
    LOGGER = logging.getLogger(__name__ + ".adjust_control_points")
    points = segment.coordinates
    target_point_count = round(segment.jamsTime / sec_interval)

    # Не требуется корректировка если количество точек уже удовлетворяет условию
    if len(points) == target_point_count:
        return points

    interpolated_points = []
    # Генерация точек путем интерполяции
    for i in range(len(points) - 1):
        # текущий контрольный фрагмент между двумя точками
        start_point = points[i]
        end_point = points[i + 1]
        interpolated_points.append(start_point)

        # Рассчитываем количество точек, которое нужно интерполировать между текущей и следующей
        points_to_add = target_point_count // len(points) - 1
        for j in range(points_to_add):
            # Рассчитываем долю пути между двумя точками
            fraction = (j + 1) / (points_to_add + 1)
            interpolated_points.append(interpolate_coordinates(start_point, end_point, fraction, j + 1))

    interpolated_points.append(points[-1])  # Добавляем последнюю точку

    # В случае, если количество интерполированных точек меньше требуемого, добавляем ещё точек,
    # интерполируя между первой и последней
    i = 0
    while len(interpolated_points) < target_point_count:
        i += 1
        interpolated_points.append(interpolate_coordinates(interpolated_points[-1], points[0], 0.5, i))

    while len(interpolated_points) > target_point_count:
        interpolated_points.pop(random.randrange(len(interpolated_points)))
    return interpolated_points


def get_cur_point(imei):
    LOGGER = logging.getLogger(__name__ + ".get_cur_point")
    try:
        connection_params = pika.ConnectionParameters(
            host=MQ.host,
            port=MQ.port,
            virtual_host=f'{MQ.vhost}',
            credentials=pika.PlainCredentials(
                username=MQ.user,
                password=MQ.password
            )
        )
        connection = pika.BlockingConnection(connection_params)
        channel = connection.channel()
        # Получите одно сообщение из очереди
        method_frame, header_frame, body = channel.basic_get(queue=f'{imei}_base', auto_ack=False)
        connection.close()
        if method_frame:
            print(method_frame, header_frame, body)
            # Обработайте сообщение здесь
            # ...
            m = model.Point.from_b64(body)
            return m.to_dict()
            # Помните, чтобы наконец удалить сообщение, вам нужно будет явно подтвердить его обработку:
            # channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        else:
            return None

    except ChannelClosedByBroker as che:
        LOGGER.error("%s: " + f"{che.reply_code} : {che.reply_text}", config.name, exc_info=True)
        return None

    except Exception as e:
        LOGGER.error("%s: " + str(e), config.name, exc_info=True)
        get_cur_point(imei)


class EgtsService:
    def __init__(self, device_imei, reg_number=None):
        self.total_ttl = None
        self.current_point = None
        LOGGER = logging.getLogger(__name__ + ".EgtsService--init")
        # super().__init__()
        # self._stop_event = threading.Event()
        self.reg_number = reg_number
        self.msg_count = 0
        self.imei = device_imei
        self.rid = None
        self.mq_channel = None
        self.mq_conn = None
        self.route = None
        self.rhead = {
            'Content-Type': 'application/json'
        }
        self.connect_to_mq()

    # def stop(self):
    #     self._stop_event.set()

    def vhosts_list(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--vhosts_list")
        r = requests.get(
            url=f'http://{MQ.host}:{MQ.apiport}/api/vhosts',
            auth=HTTPBasicAuth(MQ.user, MQ.password),
            headers=self.rhead
        )
        if r.status_code == 200:
            return r.json()

    def vhost_add(self, vhost):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--vhost_add")
        r = requests.put(
            url=f'http://{MQ.host}:{MQ.apiport}/api/vhosts/{vhost}',
            auth=HTTPBasicAuth(MQ.user, MQ.password),
            headers=self.rhead
        )
        if r.status_code == 201:
            return True

    def connect_to_mq(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--connect_to_mq")
        connection_params = pika.ConnectionParameters(
            host=MQ.host,
            port=MQ.port,
            virtual_host=f'{MQ.vhost}',
            credentials=pika.PlainCredentials(
                username=MQ.user,
                password=MQ.password
            )
        )

        try:
            # Установка соединения
            self.mq_conn = pika.BlockingConnection(connection_params)
        except Exception as e:
            if self.vhost_add(MQ.vhost):
                self.mq_conn = pika.BlockingConnection(connection_params)

        # Создание канала
        self.mq_channel = self.mq_conn.channel()

        # Имя очереди
        queue_name = str(self.imei)
        # try:
        #     r = requests.delete(
        #         url=f'http://{MQ.host}:{MQ.apiport}/api/exchanges/{MQ.vhost}/{self.imei}_ex',
        #         auth=HTTPBasicAuth(MQ.user, MQ.password),
        #         headers=self.rhead
        #     )
        # except:
        #     pass
        # Создание очереди (если не существует)
        try:
            #self.mq_channel.exchange_declare(exchange=f'{queue_name}_ex', exchange_type='direct', durable=True,
            #                                 auto_delete=False)
            self.mq_channel.exchange_declare(exchange=f'egts.emulator', exchange_type='direct', durable=True,
                                             auto_delete=False)
        except: pass
        try:
            self.base_queue = self.mq_channel.queue_declare(queue=f'{queue_name}_base', auto_delete=False, durable=True,
                                                            arguments={
                                                                #'x-expires': 120000,
                                                                #'x-dead-letter-exchange': f'{queue_name}_ex'
                                                                'x-dead-letter-exchange': 'egts.emulator'#,
                                                                #'x-dead-letter-routing-key': f'{queue_name}'
                                                                # DLX для перенаправления сообщений
                                                            })
        except: pass
        try:
            self.queue = self.mq_channel.queue_declare(queue=queue_name, auto_delete=False, durable=True)
        except:
            pass

        try:
            #self.mq_channel.queue_bind(exchange=f'{queue_name}_ex', queue=queue_name, routing_key=f'{queue_name}_base')
            self.mq_channel.queue_bind(exchange=f'egts.emulator', queue=queue_name, routing_key=f'{queue_name}_base')
        except: pass

        try:
            self.msg_count = self.queue.method.message_count
        except Exception as e:
            LOGGER.error("%s: " + str(e), config.name, exc_info=True)

    def mq_send_base(self, msg, sleep_time_sec=None, point=True):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--mq_send_base")
        if self.mq_conn and self.mq_channel:
            if point:
                # mess = msg.to_egts_packet(self.imei, round(self.total_ttl))
                mess = msg.to_b64()
            else:
                mess = msg
                LOGGER.info(f"Sent: '{self.imei} EOF'")
            if sleep_time_sec:
                self.total_ttl += sleep_time_sec * 1000
                self.mq_channel.basic_publish(
                    exchange='',
                    routing_key=str(self.imei) + '_base',
                    body=mess,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Сообщение постоянное
                        expiration=str(self.total_ttl)  # TTL  устанавливаем для этого сообщения
                    )
                )
            else:
                self.mq_channel.basic_publish(
                    exchange='',
                    routing_key=str(self.imei) + '_base',
                    body=mess,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Сообщение постоянное
                        expiration=str(self.total_ttl)  # TTL  устанавливаем для этого сообщения
                    )
                )
            try:
                message = f"Sent: 'LAT {msg.latitude}, LONG {msg.longitude}, SPEED {msg.speed}, ANGLE {msg.angle}'"
            except:
                message = f"Sent: 'EOF'"
            #LOGGER.info(message)
            return message
        else:
            LOGGER.info("NOT CONNECTED TO RMQ")
            self.connect_to_mq()
            self.mq_send_base(msg)

    def mq_send(self, msg):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--mq_send")
        if self.mq_conn and self.mq_channel:
            self.mq_channel.basic_publish(
                exchange='',
                routing_key=str(self.imei),
                # body=msg.to_egts_packet(self.imei)
                body=msg.to_b64()
            )
            return f"Sent: 'LAT {msg.latitude}, LONG {msg.longitude}, SPPED {msg.speed}, ANGLE {msg.angle}'"
        else:
            self.connect_to_mq()
            self.mq_send(msg)

    def mq_send_eof(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--mq_send_eof")
        msg = int(0).to_bytes(64, byteorder='little')
        if self.mq_conn and self.mq_channel:
            try:
                self.mq_channel.basic_publish(
                    exchange='',
                    routing_key=str(self.imei),
                    body=msg
                )
                self.mq_conn.close()
                tid = self.rid
                r = requests.get(
                    f"http://api-external.tm.8525.ru/rnis/emulationCompleted?token=5jossnicxhn75lht7aimal7r2ocvg6o7&taskId={tid}&imei={self.imei}",
                    verify=False)
                LOGGER.info("%s: " + f"Sent: '{self.imei} EOF'", config.name)
                return f"Sent: '{self.imei} EOF'"
            except:
                self.connect_to_mq()
                self.mq_send_eof()
        else:
            self.connect_to_mq()
            self.mq_send_eof()

    def disconnect_from_mq(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--disconnect_from_mq")
        self.mq_conn.close()

    def get_route_from_ext(self, rid):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--get_route_from_ext")
        self.rid = rid
        LOGGER.info(f"Start getting route for {self.imei}")
        route = ApiService.getRoute(self.rid)
        if route:
            json.dump(route, open('route.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
            self.route = Route(**route)
        if self.route:
            if self.route.ok:
                self.calc_points()
            else:
                LOGGER.info("%s: " + f"{route}", config.name)
        LOGGER.info(f"Stop getting route for {self.imei}")

    def calc_points(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--calc_points")
        self.init_points = []
        config.coord_id_now = 0
        for segment in self.route.results:
            speed = round((segment.length / segment.jamsTime) * 3.6)
            if not speed:
                speed = 0
            segment.coordinates = adjust_control_points(segment)
            for point in segment.coordinates:
                # coord_id += 1
                i = segment.coordinates.index(point)
                lat_rand = random.randint(-1, 1) / 1000000
                long_rand = random.randint(-1, 1) / 1000000
                speed_random_index = (random.random() - 0.5) * (speed / 20)
                # point.coordinatesId = coord_id
                # if point.coordinatesId is None:
                #     point.coordinatesId = segment.coordinates[segment.coordinates.index(point)-1].coordinatesId+0.001
                point.speed = int(round(speed + speed_random_index))
                # LOGGER.info("%s: " + point.speed, config.name)
                point.latitude = point.latitude + lat_rand
                point.longitude = point.longitude + long_rand
                point.tid = self.rid
                point.regnumber = self.reg_number
                lat = point.latitude
                long = point.longitude
                # config.coord_id_now = point.coordinatesId
                if i < len(segment.coordinates) - 1:
                    # LOGGER.info("%s: " + f'i: {i + 1}, len: {len(segment.coordinates)}', config.name)
                    coord_next = segment.coordinates[i + 1]
                    point.angle = int(math.atan2(coord_next.longitude - point.longitude,
                                                 coord_next.latitude - point.latitude) * 180 / math.pi)
                    # point.angle = point.angle - 180
                    if point.angle < 0:
                        point.angle = 360 + point.angle
                else:
                    point.angle = segment.coordinates[i - 1].angle
                self.init_points.append(point)
            if segment.sleep and segment.sleep != 0:
                config.coord_id_now += 1
                for sec in range(segment.sleep):
                    lat_rand = random.randint(-1, 1) / 1000000
                    long_rand = random.randint(-1, 1) / 1000000
                    self.init_points.append(
                        Point(
                            coordinatesId=config.coord_id_now,
                            latitude=lat + lat_rand,
                            longitude=long + long_rand,
                            speed=0,
                            angle=0,
                            sleeper=True,
                            # sleeper=False,
                            regnumber=self.reg_number,
                            tid=self.rid,
                            sleep_time=segment.sleep)
                    )
        self.init_points.append(base64.b64encode(int(0).to_bytes(64, byteorder='little')))
        # self.init_points = sorted(self.init_points, key=lambda point: point.coordinatesId)

    def callback_mq_send(self, point):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--callback_mq_send")
        try:
            return self.mq_send(point)
        except:
            self.connect_to_mq()
            return self.mq_send(point)

    def get_cur_point(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--get_cur_point")
        try:
            # Получите одно сообщение из очереди
            method_frame, header_frame, body = self.mq_channel.basic_get(queue=f'{self.imei}_base', auto_ack=False)

            if method_frame:
                print(method_frame, header_frame, body)
                # Обработайте сообщение здесь
                # ...
                try:
                    m = model.Point.from_b64(body)
                    return m.to_dict()
                except Exception as e:
                    return {
                        "coordinatesId": 0,
                        "tid": self.rid,
                        "speed": 0,
                        "angle": 0,
                        "sleeper": False,
                        "sleep_time": 0,
                        "timestamp": 0,
                        "regnumber": self.reg_number
                    }
                # Помните, чтобы наконец удалить сообщение, вам нужно будет явно подтвердить его обработку:
                # channel.basic_ack(delivery_tag=method_frame.delivery_tag)
            else:
                return None
        except:
            self.connect_to_mq()
            self.get_cur_point()

        # LOGGER.info("%s: " + f"ID({point.coordinatesId}) {point.angle} {point.speed} {point.latitude} {point.longitude}", config.name)

    def clear_queue(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--clear_queue")
        self.mq_channel.queue_purge(queue=self.imei)
        return True

    def delete_queue(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--delete_queue")
        self.mq_channel.queue_delete(queue=self.imei)
        #self.mq_channel
        return True

    def push_all_points(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--push_all_points")
        self.total_ttl = 0
        total_ttl = 0
        init_sleep_ts = 0
        sleep_flag = False
        dt_start = round(datetime.datetime.now(datetime.UTC).replace(tzinfo=None).timestamp())
        LOGGER.info(f"Sending {len(self.init_points)} points...")
        for point in self.init_points:
            ts = dt_start + round(total_ttl / 1000)
            try:
                point.timestamp = ts
                if point.sleeper:
                    if sleep_flag is False:
                        init_sleep_ts = ts
                    sleep_elapsed = round(init_sleep_ts + point.sleep_time - ts)
                    point.sleep_time = sleep_elapsed
                else:
                    sleep_flag = True
                self.current_point = point
                resp = self.mq_send_base(point)
            except Exception as e:
                LOGGER.warning(e, exc_info=True)
                resp = self.mq_send_base(point, point=False)
            LOGGER.debug(f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}")
            self.total_ttl += config.sec_interval * 1000
            total_ttl += config.sec_interval * 1000
        #self.mq_send_base(int(0).to_bytes(64, byteorder='little'), point=False)
        #self.mq_send_base(int(0).to_bytes(64, byteorder='little'))

        LOGGER.info(f"Sent {len(self.init_points)} points to {self.imei}")

    def push_points_to_mq(self, latency=0, force=False):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--push_points_to_mq")
        msgs = self.mq_get_messages()
        if msgs == 0:
            for point in self.init_points:
                if not self._stop_event.is_set():
                    ts = round(datetime.datetime.now(datetime.UTC).replace(tzinfo=None).timestamp())
                    point.timestamp = ts
                    self.current_point = point
                    # if point.sleeper is False:
                    resp = self.callback_mq_send(point)
                    LOGGER.info("%s: " + f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}",
                                config.name)
                    # LOGGER.info("%s: " + f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}", config.name)
                    time.sleep(latency)  # Задержка в 1 секунду
                    # else:
                    #     time.sleep(point.sleep_time)
                else:
                    break
            self.init_points = []
            return True
        else:
            LOGGER.info("%s: " + 'Очередь не пуста!', config.name)
            if force:
                self.clear_queue()
                self.push_points_to_mq(latency=latency)
            return False

    def mq_get_messages(self):
        LOGGER = logging.getLogger(__name__ + ".EgtsService--mq_get_messages")
        method_frame, header_frame, body = self.mq_channel.basic_get(queue=self.imei, auto_ack=False)
        try:
            self.msg_count = method_frame.message_count
        except AttributeError as e:
            self.msg_count = 0
        return self.msg_count


# def process_thread(imei, route_id, sec_interval=1, force=False):
#     srv = EgtsService(imei)
#     srv.get_route_from_ext(int(route_id))
#     srv.push_points_to_mq(sec_interval, force=force)


def add_imei(imei, route_id, regNumber, sec_interval=1, new_format=0, force=False):
    LOGGER = logging.getLogger(__name__ + ".add_imei")
    LOGGER.info("%s: " + f"IMEI: {imei}, ROUTE: {route_id}, INTERVAL: {sec_interval}, FORMAT: {new_format}",
                config.name)

    ########## DB ###############

    #############################

    if imei not in imeis:
        #if new_format == 1:
        LOGGER.info("%s: " + f"Inserting route for {imei}", config.name)
        config.threads[imei] = EgtsService(imei, regNumber)
        config.threads[imei].get_route_from_ext(int(route_id))
        imeis.append(imei)
        LOGGER.info(f"IMEI: {imei}, ROUTE: {route_id}, POINTS: {len(config.threads[imei].init_points)}")
        config.threads[imei].push_all_points()
        # else:
        #     LOGGER.info("%s: " + f'Started thread {imei} with {sec_interval} seconds interval', config.name)
        #     config.threads[imei] = EgtsService(imei, regNumber)
        #     config.threads[imei].get_route_from_ext(int(route_id))
        #     imeis.append(imei)
        #     LOGGER.info("%s: " + f"IMEI: {imei}, ROUTE: {route_id}, POINTS: {len(config.threads[imei].init_points)}",
        #                 config.name)
        #     config.threads[imei].push_points_to_mq(sec_interval, force=force)
        #     config.threads[imei].mq_send_eof()
        try:
            imeis.remove(imei)
        except:
            pass
        # stop_imei(imei)
        # LOGGER.info("%s: " + f'Finished thread {imei}', config.name)


# def stop_imei(imei):
#     tid = int(str(imei)[-8:])
#     if config.threads.get(imei, None):
#         config.threads[imei].stop()
#         d = {
#             'status': 'stopped',
#             'id': tid,
#             'imei': imei
#         }
#         try:
#             route = config.threads[imei].rid
#             d['route'] = route
#         except:
#             d['route'] = None
#         try:
#             d['point'] = config.threads[imei].current_point.to_dict()
#             d['point'].pop('coordinatesId')
#         except:
#             d['point'] = None
#         try:
#             config.threads.pop(imei)
#         except:
#             pass
#         return d
#     else:
#         d = {
#             'status': 'not exists',
#             'id': tid,
#             'imei': imei,
#             'route': None,
#         }
#         return d


def queues_list():
    LOGGER = logging.getLogger(__name__ + ".queues_list")
    r = requests.get(f"http://{MQ.host}:{MQ.apiport}/api/queues", auth=(MQ.user, MQ.password), verify=False,
                     proxies=None)
    js = r.json()
    # LOGGER.info("%s: " + js, config.name)
    queues = []
    for item in js:
        if item.get('vhost', None) == MQ.vhost:
            name = item.get('name')
            try:
                queues.append(int(name))
            except:
                pass
    return queues


def get_base_queues():
    LOGGER = logging.getLogger(__name__ + ".get_base_queues")
    url_base = f"http://{MQ.host}:{MQ.apiport}/api/queues/{MQ.vhost}"
    result = []
    try:
        r = requests.get(url_base, auth=(MQ.user, MQ.password), verify=False, proxies=None)
        items = r.json()
        for i in items:
            name = i.get("name", None)
            if name.find('base') > -1:
                result.append(name.split('_')[0])
    except Exception as e:
        LOGGER.error("%s: " + str(e), config.name, exc_info=True)
    return result


def get_imeis(imeis=None):
    LOGGER = logging.getLogger(__name__ + ".get_imeis")
    if not imeis:
        imeis = get_base_queues()
    else:
        if isinstance(imeis, str):
            imeis = [i.strip() for i in imeis.split(',')]
        elif isinstance(imeis, list):
            pass
        else:
            imeis = []
    result = []
    for imei in imeis:
        info = None
        info = get_imei(imei)
        if info.get('status', 'not exists') != 'not exists':
            info['imei'] = imei
            result.append(dict(info))
    return result


def get_imei(imei):
    LOGGER = logging.getLogger(__name__ + ".get_imei")
    url_base = f"http://{MQ.host}:{MQ.apiport}/api/queues/{MQ.vhost}/{imei}_base"
    tid = int(str(imei)[-8:])
    try:
        r = requests.get(url_base, auth=(MQ.user, MQ.password), verify=False, proxies=None)
        count = r.json().get('messages', 0)
        if count > 0:
            point = get_cur_point(imei)
            route = point.get('tid', None)
            try:
                regnumber = point.get('regnumber', None)
            except:
                regnumber = None
            d = {
                'status': 'running',
                'id': tid,
                'imei': imei,
                'route': route,
                'regNumber': regnumber
            }
            try:
                d['point'] = point
                d['point'].pop('coordinatesId')
                d['point'].pop('tid')
                d['point'].pop('regnumber')
            except:
                d['point'] = None
            if point.get('timestamp', None) == 0:
                try:
                    d.pop('timestamp')
                except:
                    pass
                d['status'] = 'ending...'
                return d

            return d
        else:
            d = {
                'status': 'not exists',
                'id': tid,
                'imei': imei,
                'route': None,
            }
            return d
    except Exception as e:
        d = {
            'status': 'not exists',
            'id': tid,
            'imei': imei,
            'route': None,
        }
        return d


#
def stop_imei(imei):
    LOGGER = logging.getLogger(__name__ + ".stop_imei")
    url_base = f"http://{MQ.host}:{MQ.apiport}/api/queues/{MQ.vhost}/{imei}_base"
    tid = int(str(imei)[-8:])
    try:
        point = get_cur_point(imei)
        route = point.get('tid', None)
        r = requests.delete(url_base, auth=(MQ.user, MQ.password), verify=False, proxies=None)
        status = r.status_code
        if status == 204:
            d = {
                'status': 'stopped',
                'id': tid,
                'imei': imei,
                'route': route
            }

            try:
                d['point'] = point
                d['point'].pop('coordinatesId')
                d['point'].pop('tid')
                d['point'].pop('regnumber')
            except:
                d['point'] = None
            if point.get('timestamp', None) == 0:
                try:
                    d.pop('timestamp')
                except:
                    pass
                d['status'] = 'ending...'
                return d
            # try:
            #     r_cb = requests.get(
            #         f"http://api-external.tm.8525.ru/rnis/emulationCompleted?token=5jossnicxhn75lht7aimal7r2ocvg6o7&taskId={route}&imei={imei}",
            #         verify=False)
            # except:
            #     pass
            return d
        else:
            d = {
                'status': 'not exists',
                'id': tid,
                'imei': imei,
                'route': None,
            }
            return d
    except Exception as e:
        d = {
            'status': 'not exists',
            'id': tid,
            'imei': imei,
            'route': None,
        }
        return d


# def get_imei_point(imei):
#     tid = int(str(imei)[-8:])
#     if config.threads.get(imei, None):
#         d = {
#             'status': 'running',
#             'id':tid,
#             'imei': imei
#         }
#         # try:
#         #     route = config.threads[imei].rid
#         #     d['route'] = route
#         # except:
#         #     d['route'] = None
#         try:
#             d['point'] = get_cur_point(imei)
#             d['point'].pop('coordinatesId')
#         except:
#             d['point'] = None
#
#         return d
#     else:
#         d = {
#             'status': 'not exists',
#             'id': tid,
#             'imei': imei,
#             'route': None,
#         }
#         return d


if __name__ == '__main__':
    LOGGER = logging.getLogger(__name__)
    srv = EgtsService("358480081523995")
    srv.get_route_from_ext(22)
    srv.push_points_to_mq(sec_interval, force=True)

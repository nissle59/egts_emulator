import json
import math
import random
import socket
import time
import requests
from requests.auth import HTTPBasicAuth
import geopy
import pika
import socks
import threading

import config
from ApiService import ApiService
from EGTStrack import EGTStrack
from model import *
from config import MQ, sec_interval

imeis = []

config.coord_id_now = 0


class StoppableThread(threading.Thread):
    def __init__(self, target, args=()):
        super().__init__()
        self._stop_event = threading.Event()
        self._target = target
        self._args = args

    def run(self):
        # Пока флаг остановки не установлен, запускаем целевую функцию
        while not self._stop_event.is_set():
            self._target(*self._args)
            # Если функция 'target' быстро завершается и вы хотите
            # запускать ее многократно, рассмотрите возможность добавления sleep
            # Если 'target' - долгая функция, которая должна сама следить
            # за _stop_event, то следите за этим внутри 'target'

    def stop(self):
        self._stop_event.set()


def interpolate_coordinates(point_a, point_b, fraction, cur_point):
    """Интерполирует координаты между двумя точками."""
    config.coord_id_now += 1
    lat_diff = point_b.latitude - point_a.latitude
    lon_diff = point_b.longitude - point_a.longitude
    lat = point_a.latitude + fraction * lat_diff
    lon = point_a.longitude + fraction * lon_diff
    return Point(
        #coordinatesId=point_a.coordinatesId + 0.001 * cur_point,
        coordinatesId=config.coord_id_now,
        latitude=float("{0:.6f}".format(round(lat * 1000000) / 1000000)),
        longitude=float("{0:.6f}".format(round(lon * 1000000) / 1000000))
    )


def adjust_control_points(segment):
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


class EgtsService(threading.Thread):
    def __init__(self, device_imei):
        super().__init__()
        self._stop_event = threading.Event()
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

    def stop(self):
        self._stop_event.set()

    def vhosts_list(self):
        r = requests.get(
            url=f'http://{MQ.host}:{MQ.apiport}/api/vhosts',
            auth=HTTPBasicAuth(MQ.user, MQ.password),
            headers=self.rhead
        )
        if r.status_code == 200:
            return r.json()

    def vhost_add(self, vhost):
        r = requests.put(
            url=f'http://{MQ.host}:{MQ.apiport}/api/vhosts/{vhost}',
            auth=HTTPBasicAuth(MQ.user, MQ.password),
            headers=self.rhead
        )
        if r.status_code == 201:
            return True

    def connect_to_mq(self):
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

        # Создание очереди (если не существует)
        self.queue = self.mq_channel.queue_declare(queue=queue_name, auto_delete=False, durable=True)
        self.base_queue = self.mq_channel.queue_declare(queue=f'{queue_name}_base',auto_delete=True, durable=True, arguments={
            'x-message-ttl': config.sec_interval * 1000,  # TTL в миллисекундах
            'x-dead-letter-exchange': queue_name  # DLX для перенаправления сообщений
        })

        try:
            self.msg_count = self.queue.method.message_count
        except Exception as e:
            config.logger.info(e)


    def mq_send_base(self, msg, sleep_time_sec = None):
        if self.mq_conn and self.mq_channel:
            if sleep_time_sec:
                message_ttl = sleep_time_sec * 1000
                self.mq_channel.basic_publish(
                    exchange='',
                    routing_key=str(self.imei)+'_base',
                    body=msg.to_egts_packet(self.imei),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Сообщение постоянное
                        expiration=str(message_ttl)  # TTL  устанавливаем для этого сообщения
                    )
                )
                return f"Sent: 'LAT {msg.latitude}, LONG {msg.longitude}, SLEEP: {sleep_time_sec} second(s)'"
            else:
                self.mq_channel.basic_publish(
                    exchange='',
                    routing_key=str(self.imei)+'_base',
                    body=msg.to_egts_packet(self.imei)
                )
                return f"Sent: 'LAT {msg.latitude}, LONG {msg.longitude}, SPPED {msg.speed}, ANGLE {msg.angle}'"
        else:
            self.connect_to_mq()
            self.mq_send_base(msg)


    def mq_send(self, msg):
        if self.mq_conn and self.mq_channel:
            self.mq_channel.basic_publish(
                exchange='',
                routing_key=str(self.imei),
                body=msg.to_egts_packet(self.imei)
            )
            return f"Sent: 'LAT {msg.latitude}, LONG {msg.longitude}, SPPED {msg.speed}, ANGLE {msg.angle}'"
        else:
            self.connect_to_mq()
            self.mq_send(msg)

    def mq_send_eof(self):
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
                r = requests.get(f"http://api-external.tm.8525.ru/rnis/emulationCompleted?token=5jossnicxhn75lht7aimal7r2ocvg6o7&taskId={tid}&imei={self.imei}", verify=False)
                config.logger.info(f"Sent: '{self.imei} EOF'")
                return f"Sent: '{self.imei} EOF'"
            except:
                self.connect_to_mq()
                self.mq_send_eof()
        else:
            self.connect_to_mq()
            self.mq_send_eof()

    def disconnect_from_mq(self):
        self.mq_conn.close()

    def get_route_from_ext(self, rid):
        self.rid = rid
        route = ApiService.getRoute(self.rid)
        if route:
            json.dump(route, open('route.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
            self.route = Route(**route)
        if self.route:
            if self.route.ok:
                self.calc_points()
            else:
                config.logger.info(f"{route}")

    def calc_points(self):
        self.init_points = []
        config.coord_id_now = 0
        for segment in self.route.results:
            speed = round((segment.length / segment.jamsTime) * 3.6)
            if not speed:
                speed = 0
            segment.coordinates = adjust_control_points(segment)
            for point in segment.coordinates:
                #coord_id += 1
                i = segment.coordinates.index(point)
                lat_rand = random.randint(-1, 1) / 1000000
                long_rand = random.randint(-1, 1) / 1000000
                speed_random_index = (random.random() - 0.5) * (speed / 20)
                #point.coordinatesId = coord_id
                # if point.coordinatesId is None:
                #     point.coordinatesId = segment.coordinates[segment.coordinates.index(point)-1].coordinatesId+0.001
                point.speed = int(round(speed + speed_random_index))
                # config.logger.info(point.speed)
                point.latitude = point.latitude + lat_rand
                point.longitude = point.longitude + long_rand
                lat = point.latitude
                long = point.longitude
                #config.coord_id_now = point.coordinatesId
                if i < len(segment.coordinates) - 1:
                    config.logger.info(f'i: {i + 1}, len: {len(segment.coordinates)}')
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
                self.init_points.append(
                    Point(
                        coordinatesId=config.coord_id_now,
                        latitude=lat,
                        longitude=long,
                        speed=0,
                        angle=0,
                        sleeper=True,
                        sleep_time=segment.sleep)
                )
        #self.init_points = sorted(self.init_points, key=lambda point: point.coordinatesId)

    def callback_mq_send(self, point):
        try:
            return self.mq_send(point)
        except:
            self.connect_to_mq()
            return self.mq_send(point)

        # config.logger.info(f"ID({point.coordinatesId}) {point.angle} {point.speed} {point.latitude} {point.longitude}")

    def clear_queue(self):
        self.mq_channel.queue_purge(queue=self.imei)
        return True

    def delete_queue(self):
        self.mq_channel.queue_delete(queue=self.imei)
        return True

    def push_all_points(self):
        for point in self.init_points:
            self.current_point = point
            if point.sleeper is False:
                resp = self.mq_send(point)
                # config.logger.info(f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}")
                # config.logger.info(f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}")
            else:
                resp = self.mq_send(point, point.sleep_time)
        self.mq_send(int(0).to_bytes(64, byteorder='little'))

    def push_points_to_mq(self, latency=0, force=False):
        msgs = self.mq_get_messages()
        if msgs == 0:
            for point in self.init_points:
                if not self._stop_event.is_set():
                    self.current_point = point
                    if point.sleeper is False:
                        resp = self.callback_mq_send(point)
                        config.logger.info(f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}")
                        #config.logger.info(f"Point {self.init_points.index(point)} of {len(self.init_points)}, {resp}")
                        time.sleep(latency)  # Задержка в 1 секунду
                    else:
                        time.sleep(point.sleep_time)
                else:
                    break
            self.init_points = []
            return True
        else:
            config.logger.info('Очередь не пуста!')
            if force:
                self.clear_queue()
                self.push_points_to_mq(latency=latency)
            return False

    def mq_get_messages(self):
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


def add_imei(imei, route_id, sec_interval=1, new_format=0, force=False):
    if imei not in imeis:
        if new_format == 1:
            config.logger.info(f"Inserting route for {imei}")
            config.threads[imei] = EgtsService(imei)
            config.threads[imei].get_route_from_ext(int(route_id))
            imeis.append(imei)
            config.threads[imei].push_all_points()
        else:
            config.logger.info(f'Started thread {imei} with {sec_interval} seconds interval')
            config.threads[imei] = EgtsService(imei)
            config.threads[imei].get_route_from_ext(int(route_id))
            imeis.append(imei)
            config.threads[imei].push_points_to_mq(sec_interval, force=force)
            config.threads[imei].mq_send_eof()
        try:
            imeis.remove(imei)
        except:
            pass
        stop_imei(imei)
        config.logger.info(f'Finished thread {imei}')


def stop_imei(imei):
    tid = int(str(imei)[-8:])
    if config.threads.get(imei, None):
        config.threads[imei].stop()
        d = {
            'status': 'stopped',
            'id': tid,
            'imei': imei
        }
        try:
            route = config.threads[imei].rid
            d['route'] = route
        except:
            d['route'] = None
        try:
            d['point'] = config.threads[imei].current_point.to_dict()
            d['point'].pop('coordinatesId')
        except:
            d['point'] = None
        try:
            config.threads.pop(imei)
        except:
            pass
        return d
    else:
        d = {
            'status': 'not exists',
            'id': tid,
            'imei': imei,
            'route': None,
        }
        return d


def get_imei_point(imei):
    tid = int(str(imei)[-8:])
    if config.threads.get(imei, None):
        d = {
            'status': 'running',
            'id':tid,
            'imei': imei
        }
        try:
            route = config.threads[imei].rid
            d['route'] = route
        except:
            d['route'] = None
        try:
            d['point'] = config.threads[imei].current_point.to_dict()
            d['point'].pop('coordinatesId')
        except:
            d['point'] = None

        return d
    else:
        d = {
            'status': 'not exists',
            'id': tid,
            'imei': imei,
            'route': None,
        }
        return d


if __name__ == '__main__':
    srv = EgtsService("358480081523995")
    srv.get_route_from_ext(22)
    srv.push_points_to_mq(sec_interval, force=True)

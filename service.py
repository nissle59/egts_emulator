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

from ApiService import ApiService
from EGTStrack import EGTStrack
from model import *
from config import MQ


def interpolate_coordinates(point_a, point_b, fraction, cur_point):
    """Интерполирует координаты между двумя точками."""
    lat_diff = point_b.latitude - point_a.latitude
    lon_diff = point_b.longitude - point_a.longitude
    lat = point_a.latitude + fraction * lat_diff
    lon = point_a.longitude + fraction * lon_diff
    return Point(
        coordinatesId=point_a.coordinatesId + 0.001 * cur_point,
        latitude=float("{0:.6f}".format(lat)),
        longitude=float("{0:.6f}".format(lon))
    )


def adjust_control_points(segment):
    points = segment.coordinates
    target_point_count = round(segment.jamsTime)

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


class EgtsService:
    def __init__(self, device_imei):
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
        self.queue = self.mq_channel.queue_declare(queue=queue_name, auto_delete=False)
        try:
            self.msg_count = self.queue.method.message_count
        except Exception as e:
            print(e)

    def mq_send(self, msg):
        if self.mq_conn and self.mq_channel:
            self.mq_channel.basic_publish(
                exchange='',
                routing_key=str(self.imei),
                body=msg.to_egts_packet(self.imei)
            )
            print(f"Sent: '{msg}'")
        else:
            self.connect_to_mq()
            self.mq_send(msg.to_json())

    def disconnect_from_mq(self):
        self.mq_conn.close()

    def get_route_from_ext(self, rid):
        self.rid = rid
        route = ApiService.getRoute(self.rid)
        if route:
            json.dump(route, open('route.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
            self.route = Route(**route)
        if self.route:
            self.calc_points()

    def calc_points(self):
        self.init_points = []
        for segment in self.route.segments:
            speed = round((segment.length / segment.jamsTime) * 3.6)
            if not speed:
                speed = 0
            segment.coordinates = adjust_control_points(segment)
            for point in segment.coordinates:
                i = segment.coordinates.index(point)
                lat_rand = random.randint(-1, 1) / 1000000
                long_rand = random.randint(-1, 1) / 1000000
                speed_random_index = (random.random() - 0.5) * (speed / 20)
                point.coordinatesId = float(point.coordinatesId)
                point.speed = int(round(speed + speed_random_index))
                # print(point.speed)
                point.latitude = point.latitude + lat_rand
                point.longitude = point.longitude + long_rand
                if i < len(segment.coordinates) - 1:
                    print(f'i: {i + 1}, len: {len(segment.coordinates)}')
                    coord_next = segment.coordinates[i + 1]
                    point.angle = int(math.atan2(coord_next.longitude - point.longitude,
                                                 coord_next.latitude - point.latitude) * 180 / math.pi)
                    # point.angle = point.angle - 180
                    if point.angle < 0:
                        point.angle = 360 + point.angle
                else:
                    point.angle = segment.coordinates[i - 1].angle
                self.init_points.append(point)
        self.init_points = sorted(self.init_points, key=lambda point: point.coordinatesId)

    def callback_mq_send(self, point):
        self.mq_send(point)
        # print(f"ID({point.coordinatesId}) {point.angle} {point.speed} {point.latitude} {point.longitude}")

    def clear_queue(self):
        self.mq_channel.queue_purge(queue=self.imei)
        return True

    def delete_queue(self):
        self.mq_channel.queue_delete(queue=self.imei)
        return True

    def push_points_to_mq(self, latency=0, force=False):
        msgs = self.mq_get_messages()
        if msgs == 0:
            for point in self.init_points:
                self.callback_mq_send(point)
                time.sleep(latency)  # Задержка в 1 секунду
            return True
        else:
            print('Очередь не пуста!')
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


if __name__ == '__main__':
    srv = EgtsService("358480081523995")
    srv.get_route_from_ext(22)
    srv.push_points_to_mq(1,force=True)
    # srv.send_egts()
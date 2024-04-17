import math
import socket
import time
import sys
import datetime

from pprint import pprint
from ApiService import ApiService
from EGTStrack import EGTStrack
import socks
import random


def coords_prepare(coords):
    for coord in coords:
        coord['angle'] = random.randint(0, 359)
        if coords[i + 1]:
            coord_next = coords[i + 1]
            coord['angle'] = int(math.atan2(coord_next['longitude'] - coord['longitude'],
                                            coord_next['latitude'] - coord['latitude']) * 180 / math.pi)
            if coord['angle'] < 0:
                coord['angle'] = 360 + coord['angle']
        coord['speed'] = random.randint(25, 90)
    return coords


routeId = 22
if len(sys.argv) >= 2:
    routeId = int(sys.argv[1])
print('routeId:', routeId)

coords = ApiService.getCoordinates(routeId)
# pprint(coors)

#socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, '91.238.249.96', 49685, True, 'XkE3R0g7sT', 'pFkCAJ7yEl')

socket.socket = socks.socksocket

while True:
    try:
        sock = socket.socket()
        #sock.connect(('data.rnis.mos.ru', 4444))
        sock.connect(('46.50.138.139', 65521))
        #sock.connect(('10.8.0.1', 6000))
        #sock.connect(('127.0.0.1', 7777))
    except socket.timeout as msg:
        print("Timeouterror : %s" % msg)
        continue
    except socket.error as exc:
        print("Caught exception: %s" % exc)
        continue
    except TypeError as msg:
        print("Type Error : %s" % msg)
        continue
    except socks.GeneralProxyError as msg:
        print("GeneralProxyError : %s" % msg)
        continue
    break

# Create a class and configure the device
# cmd1 = EGTStrack(deviceid="40614705", deviceimei="358480081523999")
#

# cmd1 = EGTStrack(deviceid="0", deviceimei="40614705")
cmd1 = EGTStrack(deviceid="40614705", deviceimei="358480081523995")

message_b = cmd1.new_message()  # get message

print('CLT >> "{}"'.format(message_b.hex()))
sock.sendall(message_b)  # sends a message to the server
recv_b = sock.recv(256)  #
print('SRV >> "{}"'.format(recv_b.hex()))

i = 0
coords = coords_prepare(coords)
for coord in coords:
    cmd1.add_service(16,
                     long=coord['longitude'],
                     lat=coord['latitude'],
                     speed=coord['speed'],
                     angle=coord['angle']
                     )
    message_b = cmd1.new_message()
    print('CLT >> "{}"'.format(message_b.hex()))
    sock.sendall(message_b)
    recv_b = sock.recv(256)
    print('SRV >> "{}"'.format(recv_b.hex()))
    time.sleep(2)
    i += 1

sock.close()

if __name__ == "__main__":
    pass
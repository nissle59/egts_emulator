import logging
import sys

class MQ:
    #host = 'localhost'
    host = 'rmq.local'
    user = 'rmuser'
    password = 'rmpassword'
    port = 5672
    apiport = 15672
    vhost = 'egts'

threads = {}

sec_interval = 10
coord_id_now = 0

logging.basicConfig(level=logging.INFO)

handler = logging.FileHandler('app.log')
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
s_handler = logging.StreamHandler(sys.stdout)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.addHandler(s_handler)
logger.setLevel(logging.INFO)
logger.propagate = False
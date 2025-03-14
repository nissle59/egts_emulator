import json
import logging
import logging.config
import sys

name = "EGTS Web Service"

logging.config.dictConfig(json.load(open('logging.json', 'r')))
LOGGER = logging.getLogger(__name__)


class MQ:
    # host = 'localhost'
    host = 'rmq.db.services.local'
    user = 'rmuser'
    password = 'rmpassword'
    port = 5672
    apiport = 15672
    vhost = 'egts'


DSN = 'postgresql://postgres:psqlpass@pg.db.services.local/vindcgibdd'
DSN_DEBUG = 'postgresql://postgres:psqlpass@10.8.0.5/vindcgibdd'

threads = {}

sec_interval = 1
coord_id_now = 0

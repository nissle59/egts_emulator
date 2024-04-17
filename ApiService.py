import urllib.request
import json


class ApiService:
    base_url = 'http://transpropusk.crm.8525.ru/api/services/rnis/'

    @classmethod
    def getRoute(cls, id):
        return cls.send("route?routeId=" + str(id))

    @classmethod
    def getCoordinates(cls, id):
        return cls.send("route/coordinates?routeId=" + str(id))

    @staticmethod
    def send(url):
        req = urllib.request.Request(ApiService.base_url + url)
        with urllib.request.urlopen(req) as response:
            body = response.read()
        return json.loads(body)['results']
